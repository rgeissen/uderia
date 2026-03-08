import boto3
import json
import sys

# AWS Credentials and Region (provided by the user)

def list_bedrock_models(aws_access_key_id, aws_secret_access_key, aws_region):
    """
    Lists available foundation models (inference profiles) in AWS Bedrock.
    """
    try:
        # Create a Bedrock client
        bedrock_client = boto3.client(
            service_name='bedrock',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )

        print(f"Listing available Bedrock models in region: {aws_region}...")
        response = bedrock_client.list_foundation_models()
        
        # Filter for text generation models
        text_models = [
            model for model in response['modelSummaries']
            if 'TEXT' in model.get('inputModalities', []) and 'TEXT' in model.get('outputModalities', [])
        ]

        if not text_models:
            print("No text generation models found in the specified region.")
            return []

        print("\nAvailable Text Generation Models (Inference Profiles):")
        for i, model in enumerate(text_models):
            print(f"{i + 1}. Model ID: {model['modelId']} (Provider: {model['providerName']})")
        
        return text_models

    except Exception as e:
        print(f"Error listing Bedrock models: {e}")
        return []

def invoke_bedrock_model(aws_access_key_id, aws_secret_access_key, aws_region, model_id, prompt_text):
    """
    Invokes a selected Bedrock model with a given prompt.
    """
    try:
        # Create a Bedrock Runtime client for invoking models
        bedrock_runtime_client = boto3.client(
            service_name='bedrock-runtime',
            region_name=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key
        )

        # Adjust model_id for Nova models if they require an inference profile prefix
        # This is a common pattern for system-defined inference profiles for certain models.
        # For eu-central-1, it might be 'eu.amazon.nova-pro-v1:0'
        # For us-east-1, it might be 'us.amazon.nova-pro-v1:0'
        # The exact prefix depends on the region and how AWS names these profiles.
        adjusted_model_id = model_id
        if "amazon.nova" in model_id:
            # Attempt to use a regional prefix for Nova models
            if aws_region.startswith("us-"):
                adjusted_model_id = f"us.{model_id}"
            elif aws_region.startswith("eu-"):
                adjusted_model_id = f"eu.{model_id}"
            elif aws_region.startswith("ap-"):
                adjusted_model_id = f"apac.{model_id}"
            print(f"Attempting to use adjusted model ID for Nova: {adjusted_model_id}")


        # Determine the payload structure based on the model ID
        # This is a simplified approach; real-world applications might need more robust parsing
        # of model capabilities or specific payload structures.
        if "anthropic" in model_id:
            # Example for Anthropic Claude models
            body = json.dumps({
                "prompt": f"\n\nHuman: {prompt_text}\n\nAssistant:",
                "max_tokens_to_sample": 200,
                "temperature": 0.7,
                "top_p": 0.9
            })
        elif "amazon" in model_id and "titan" in model_id:
            # Example for Amazon Titan models
            body = json.dumps({
                "inputText": prompt_text,
                "textGenerationConfig": {
                    "maxTokenCount": 200,
                    "temperature": 0.7,
                    "topP": 0.9
                }
            })
        elif "ai21" in model_id:
            # Example for AI21 Labs Jurassic models
            body = json.dumps({
                "prompt": prompt_text,
                "maxTokens": 200,
                "temperature": 0.7,
                "topP": 0.9
            })
        elif "cohere" in model_id:
            # Example for Cohere models
            body = json.dumps({
                "prompt": prompt_text,
                "max_tokens": 200,
                "temperature": 0.7,
                "p": 0.9
            })
        elif "meta" in model_id and "llama" in model_id:
            # Example for Meta Llama models
            body = json.dumps({
                "prompt": prompt_text,
                "max_gen_len": 200,
                "temperature": 0.7,
                "top_p": 0.9
            })
        elif "amazon.nova" in model_id:
            # Example for Amazon Nova models (using Converse API as it's often preferred for Nova)
            # Note: Nova models often support the Converse API for multi-turn conversations
            # but InvokeModel can still be used for single-turn.
            # The payload structure for Nova models can be similar to Titan.
            body = json.dumps({
                "messages": [{"role": "user", "content": [{"text": prompt_text}]}],
                "inferenceConfig": {
                    "maxTokens": 200,
                    "temperature": 0.7,
                    "topP": 0.9
                }
            })
        else:
            # Default generic payload for other models
            print(f"Warning: Using a generic payload for model {model_id}. This might not work for all models.")
            body = json.dumps({
                "prompt": prompt_text,
                "max_tokens_to_sample": 200,
                "temperature": 0.7
            })

        print(f"\nInvoking model '{adjusted_model_id}' with prompt: '{prompt_text}'...")
        response = bedrock_runtime_client.invoke_model(
            body=body,
            modelId=adjusted_model_id, # Use the adjusted model ID here
            accept='application/json',
            contentType='application/json'
        )

        response_body = json.loads(response.get('body').read())

        # Extract the text based on model type
        generated_text = "Could not parse response."
        if "anthropic" in model_id:
            generated_text = response_body.get('completion', generated_text)
        elif "amazon" in model_id and "titan" in model_id:
            generated_text = response_body.get('results', [{}])[0].get('outputText', generated_text)
        elif "ai21" in model_id:
            generated_text = response_body.get('completions', [{}])[0].get('data', {}).get('text', generated_text)
        elif "cohere" in model_id:
            generated_text = response_body.get('generations', [{}])[0].get('text', generated_text)
        elif "meta" in model_id and "llama" in model_id:
            generated_text = response_body.get('generation', generated_text)
        elif "amazon.nova" in model_id:
            # For Nova models, response might be in 'content' of the first message
            if response_body.get('output', {}).get('message', {}).get('content'):
                for content_block in response_body['output']['message']['content']:
                    if 'text' in content_block:
                        generated_text = content_block['text']
                        break
            else:
                generated_text = "Nova model response structure not recognized."
        else:
            # Attempt to find common keys if model type is unknown
            if 'completion' in response_body:
                generated_text = response_body['completion']
            elif 'outputText' in response_body:
                generated_text = response_body['outputText']
            elif 'text' in response_body:
                generated_text = response_body['text']
            elif 'generated_text' in response_body:
                generated_text = response_body['generated_text']

        return generated_text

    except Exception as e:
        print(f"Error invoking Bedrock model '{model_id}' (adjusted to '{adjusted_model_id}'): {e}")
        return None

def main():
    """
    Main function to orchestrate listing models, user selection, and conversation.
    """
    # Prompt user for AWS credentials and region
    aws_access_key_id = input("Enter your AWS Access Key ID: ")
    aws_secret_access_key = input("Enter your AWS Secret Access Key: ")
    aws_region = input("Enter your AWS Region (e.g., eu-central-1): ")

    models = list_bedrock_models(aws_access_key_id, aws_secret_access_key, aws_region)

    if not models:
        print("Exiting program.")
        sys.exit(1)

    while True:
        try:
            choice = input("\nEnter the number of the model you want to use (or 'q' to quit): ")
            if choice.lower() == 'q':
                print("Exiting program.")
                break

            choice_index = int(choice) - 1
            if 0 <= choice_index < len(models):
                selected_model_id = models[choice_index]['modelId']
                print(f"You selected: {selected_model_id}")

                # Start a simple conversation
                prompt = "Hello"
                response_text = invoke_bedrock_model(
                    aws_access_key_id, aws_secret_access_key, aws_region,
                    selected_model_id, prompt
                )

                if response_text:
                    print("\n--- Model Response ---")
                    print(response_text.strip())
                    print("----------------------")
                else:
                    print("Failed to get a response from the model.")
                
                # Ask if the user wants to try another model or quit
                another_round = input("\nDo you want to try another model? (yes/no): ").lower()
                if another_round != 'yes':
                    print("Exiting program.")
                    break

            else:
                print("Invalid choice. Please enter a valid number from the list.")
        except ValueError:
            print("Invalid input. Please enter a number or 'q'.")
        except KeyboardInterrupt:
            print("\nExiting program.")
            break

if __name__ == "__main__":
    main()
