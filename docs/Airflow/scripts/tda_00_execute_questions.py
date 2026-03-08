import time
import os
import json
import requests
# Airflow 3 SDK Imports
from airflow.sdk import dag, task
from airflow.sdk import BaseHook
import pendulum # Used for start_date calculation

from airflow.sdk import Variable
# The days_ago function is removed in Airflow 3
# from airflow.utils.dates import days_ago 
from airflow.exceptions import AirflowException

# --- CONFIGURATION ---
DAG_ID = 'tda_00_execute_questions'
CONN_ID = 'tda_api_conn'

default_args = {
    'owner': 'airflow',
    'retries': 0,
}


@dag(
    dag_id=DAG_ID, 
    default_args=default_args, 
    # FIX: Replaced 'schedule_interval' with the correct parameter 'schedule' for Airflow 3
    schedule=None, 
    start_date=pendulum.now(tz="UTC").subtract(days=1), 
    tags=['tda', 'setup'], 
    catchup=False
)
def tda_execute_questions():
    """
    Uses the session / submit / poll pattern with access token authentication.
    Reads questions from `questions.txt` and requires a default profile.
    Each question is executed in a new session/query pair with async polling.
    """

    # BaseHook is now imported via airflow.sdk
    def get_base_url():
        return BaseHook.get_connection(CONN_ID).host

    # --- TASK 0: Get API Key ---
    @task()
    def get_api_key():
        """
        Get the TDA API key from an Airflow Variable.
        Requires: Airflow Variable 'tda_api_key' with a valid TDA API key.
        """
        api_key = Variable.get("tda_api_key", default=None)
        if not api_key:
            raise AirflowException(
                "Missing Airflow Variable 'tda_api_key'. "
                "Please set it to a valid TDA API key."
            )
        print("✅ TDA API key loaded.")
        return api_key.strip()

    # --- HELPER: Debug printer ---
    def log_full_request(prepped_req):
        print(f"\n--- DEBUG: SENDING HTTP REQUEST ---")
        print(f"Method: {prepped_req.method}")
        print(f"URL: {prepped_req.url}")
        print("Headers:")
        for k, v in prepped_req.headers.items():
             print(f"  {k}: {v}")
        print(f"Body: {prepped_req.body}")
        print("-----------------------------------\n")

    # --- TASK 1: Get or Create Session ---
    @task()
    def get_or_create_session(api_key: str):
        """
        Reuse existing session if tda_session_id is set, otherwise create new one.
        Requires user to have a default profile configured.
        Profile must have both LLM Provider and MCP Server.
        """
        # Check if reusing existing session
        existing_session_id = Variable.get('tda_session_id', default=None)
        if existing_session_id and len(existing_session_id.strip()) > 0:
            print(f"✅ Reusing existing session: {existing_session_id}")
            return existing_session_id.strip()
        
        # Create new session
        url = f"{get_base_url()}/api/v1/sessions"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        session = requests.Session()
        req = requests.Request('POST', url, headers=headers)
        prepped = session.prepare_request(req)

        log_full_request(prepped)

        resp = session.send(prepped, timeout=10)
        print(f"Response Status: {resp.status_code}")
        
        if resp.status_code == 400:
            error_msg = resp.json().get('error', '')
            if 'default profile' in error_msg.lower():
                raise AirflowException(
                    f"No default profile configured. {error_msg}. "
                    "Please configure a profile (LLM + MCP Server) in the UI first."
                )
        
        resp.raise_for_status()
        session_id = resp.json()['session_id']
        print(f"✅ New session created: {session_id}")
        return session_id

    # --- TASK 2: Submit Query ---
    @task()
    def submit_query(api_key: str, session_id: str, question: str):
        """
        Submit a query to a session.
        Optionally use a different profile via tda_profile_id variable.
        Returns task_id for polling.
        """
        url = f"{get_base_url()}/api/v1/sessions/{session_id}/query"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        payload = {'prompt': question}
        
        # Optional: Override profile if tda_profile_id is set
        profile_id = Variable.get('tda_profile_id', default=None)
        if profile_id and len(profile_id.strip()) > 0:
            payload['profile_id'] = profile_id.strip()
            print(f"Using profile override: {profile_id}")

        session = requests.Session()
        req = requests.Request('POST', url, json=payload, headers=headers)
        prepped = session.prepare_request(req)

        log_full_request(prepped)

        resp = session.send(prepped, timeout=10)
        print(f"Response Status: {resp.status_code}")
        resp.raise_for_status()

        task_data = resp.json()
        task_id = task_data.get('task_id')
        print(f"✅ Query submitted with task_id: {task_id}")
        return task_data

    # --- TASK 3: Poll for Completion ---
    @task()
    def poll_until_complete(api_key: str, task_start_data: dict):
        """
        Poll task status until completion.
        """
        status_url_path = task_start_data['status_url']
        full_url = f"{get_base_url()}{status_url_path}"
        headers = {"Authorization": f"Bearer {api_key}"}

        print(f"Starting polling loop for: {full_url}")

        while True:
            resp = requests.get(full_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            current_status = data.get('status')
            print(f"Current Status: {current_status}")

            if current_status in ['complete', 'error', 'cancelled']:
                print(f"Final state reached: {current_status}")
                if current_status != 'complete':
                    raise AirflowException(f"TDA Task failed with status: {current_status}")

                print(f"RESULT: {json.dumps(data.get('result'), indent=2)}")
                return data.get('result')

            time.sleep(5)

    # --- WORKFLOW DEFINITION ---
    api_key = get_api_key()
    session_id = get_or_create_session(api_key)

    # Read questions file
    dag_folder = os.path.dirname(__file__)
    questions_path = os.path.join(dag_folder, 'questions.txt')

    if not os.path.exists(questions_path):
        # Nothing to schedule if no file exists — keep DAG readable in Airflow UI
        def noop():
            print(f"No questions file found at {questions_path}; nothing to run.")
        noop()
        return

    with open(questions_path, 'r', encoding='utf-8') as fh:
        raw_lines = fh.readlines()

    questions = [ln.strip() for ln in raw_lines if ln.strip() and not ln.strip().startswith('#')]

    if not questions:
        def noop2():
            print(f"Questions file at {questions_path} is empty or only comments; nothing to run.")
        noop2()
        return

    prev_wait = None
    for idx, q in enumerate(questions, start=1):
        submit = submit_query.override(task_id=f'submit_Q{idx}')(api_key=api_key, session_id=session_id, question=q)
        wait = poll_until_complete.override(task_id=f'wait_for_Q{idx}')(api_key=api_key, task_start_data=submit)

        # Chain tasks: wait for prev before submitting next
        if prev_wait:
            prev_wait >> submit

        prev_wait = wait


execute_questions_dag = tda_execute_questions()
