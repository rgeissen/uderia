# mcp_prompt_tester_extended.py
import asyncio
import os
from langchain_mcp_adapters.client import MultiServerMCPClient
 
# --- Configuration ---
# Replace these values if your MCP server is running on a different host or port.
MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_PORT", 8001))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp/")
MCP_SERVER_URL = f"http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}"
 
# Define the server configuration for the client
SERVER_CONFIGS = {
    'teradata_mcp_server': {
        "url": MCP_SERVER_URL,
        "transport": "streamable_http"
    }
}
 
async def main():
    """
    Connects to the MCP server, fetches all available prompts,
    and prints their details including arguments and the raw data package.
    """
    print(f"--- Connecting to MCP Server at {MCP_SERVER_URL} ---")
    
    # Initialize the MCP client with the server configuration
    mcp_client = MultiServerMCPClient(SERVER_CONFIGS)
    
    try:
        # Start a session with the configured MCP server. The 'async with'
        # block handles session setup and teardown automatically.
        async with mcp_client.session("teradata_mcp_server") as session:
            print("Successfully connected. Fetching prompts...")
            
            # Retrieve the list of all available prompts
            list_prompts_result = await session.list_prompts()
            
            # Check if the result has the 'prompts' attribute and is not empty
            if not hasattr(list_prompts_result, 'prompts') or not list_prompts_result.prompts:
                print("\nNo prompts found on the server or the response format was unexpected.")
                return
 
            print(f"\n--- Found {len(list_prompts_result.prompts)} Prompts ---")
            
            # Iterate through each prompt and print its details
            for i, prompt in enumerate(list_prompts_result.prompts):
                print(f"\n{'-'*20} Prompt {i+1} {'-'*20}")
                print(f"Name:        {prompt.name}")
                print(f"Description: {prompt.description or 'No description available.'}")
                #print(f"Parameters:  {prompt.parameters or 'No parameters available.'}")
                # --- NEW ADDITION: Print the raw data package as a JSON string ---
                print(f"Raw Data:    {prompt.model_dump_json()}")
                
                # Check for and display the arguments for each prompt
                if hasattr(prompt, 'arguments') and prompt.arguments:
                    print("Arguments:")
                    for arg in prompt.arguments:
                        # Use model_dump() to get a dictionary representation of the Pydantic model
                        arg_dict = arg.model_dump()
                        print(f"  - Name:        {arg_dict.get('name')}")
                        #print(f"    Type:        {arg_dict.get('type')}")
                        print(f"    Description: {arg_dict.get('description')}")
                        print(f"    Required:    {arg_dict.get('required')}")
                else:
                    print("Arguments:   None")
            
            print(f"\n{'-'*52}")
 
    except Exception as e:
        print(f"\n--- An Error Occurred ---")
        print(f"Failed to connect to the MCP server or fetch prompts: {e}")
        print("Please ensure the MCP server is running and the configuration is correct.")
    # The 'finally' block is no longer needed as 'async with' handles cleanup.
 
if __name__ == "__main__":
    # Run the asynchronous main function
    asyncio.run(main())
 