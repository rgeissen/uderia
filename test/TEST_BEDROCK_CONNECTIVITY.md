# AWS Bedrock Connectivity Test

## Overview

`test_bedrock_connectivity.py` is a standalone test script that validates AWS Bedrock connectivity using the application's mechanics without requiring inference profiles. It provides an interactive way to test direct model invocation.

## Features

- ✅ Interactive credential input (Access Key, Secret Key, Region)
- ✅ Lists all available foundation models in the specified region
- ✅ Tests connection with selected models
- ✅ Uses the same client creation patterns as the main application
- ✅ Supports all major Bedrock model providers:
  - Anthropic (Claude)
  - Amazon (Titan, Nova)
  - AI21 Labs (Jurassic)
  - Cohere
  - Meta (Llama)
  - Mistral

## Prerequisites

- Python 3.8+
- `boto3` library installed
- Valid AWS credentials with Bedrock permissions
- Models enabled in your AWS Bedrock console for the target region

## Required IAM Permissions

Your AWS credentials need the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:ListFoundationModels",
        "bedrock-runtime:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

## Usage

### Run the Script

```bash
cd test
python test_bedrock_connectivity.py
```

Or if made executable:

```bash
cd test
./test_bedrock_connectivity.py
```

### Interactive Workflow

1. **Enter Credentials**: When prompted, provide:
   - AWS Access Key ID
   - AWS Secret Access Key
   - AWS Region (e.g., `us-east-1`, `eu-central-1`)

2. **View Available Models**: The script lists all text generation models available in your region with:
   - Model ID
   - Provider name
   - Model status

3. **Select a Model**: Enter the number corresponding to the model you want to test

4. **View Results**: The script will:
   - Create a Bedrock Runtime client
   - Send a test prompt to the model
   - Display the model's response
   - Show success/failure status

5. **Test More Models**: Choose to test another model or quit

## Example Session

```
============================================================
 AWS Bedrock Connectivity Test
============================================================

Please enter your AWS credentials:
  Access Key ID: AKIAIOSFODNN7EXAMPLE
  Secret Access Key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
  Region (e.g., us-east-1, eu-central-1): us-east-1

✓ Bedrock client created for region: us-east-1

============================================================
 Listing Available Foundation Models
============================================================

✓ Found 15 text generation models:

   1. anthropic.claude-3-sonnet-20240229-v1:0
      Provider: Anthropic
      Status: ACTIVE

   2. amazon.titan-text-express-v1
      Provider: Amazon
      Status: ACTIVE

   3. ai21.j2-ultra-v1
      Provider: AI21 Labs
      Status: ACTIVE

...

────────────────────────────────────────────────────────────
Enter model number to test (or 'q' to quit): 1

✓ Bedrock Runtime client created

============================================================
 Testing Connection with anthropic.claude-3-sonnet-20240229-v1:0
============================================================

  Sending test prompt: 'Hello! Please respond with a brief greeting.'
  Model ID: anthropic.claude-3-sonnet-20240229-v1:0

✓ Model invocation successful!

────────────────────────────────────────────────────────────
Response:
────────────────────────────────────────────────────────────
Hello! Nice to meet you. I'm Claude, an AI assistant. How can I help you today?
────────────────────────────────────────────────────────────

✓ Connectivity validated for anthropic.claude-3-sonnet-20240229-v1:0

Test another model? (yes/no): no

Exiting. Goodbye!
```

## Application Mechanics Used

This script uses the same patterns as the main application:

1. **Client Creation**: Uses `boto3.client()` with the same service names:
   - `bedrock` for listing models
   - `bedrock-runtime` for invoking models

2. **Request Body Generation**: Model-specific payload structures matching the application's handler logic

3. **Response Parsing**: Extracts text from responses using the same provider-specific logic

4. **Regional Handling**: Applies the same Nova model regional prefix logic

## Troubleshooting

### No Models Found

- Verify your AWS region is correct
- Ensure you have enabled models in the AWS Bedrock console for that region
- Check that your credentials have `bedrock:ListFoundationModels` permission

### Model Invocation Failed

- Verify the model is enabled in your AWS Bedrock console
- Check that your credentials have `bedrock-runtime:InvokeModel` permission
- Ensure you have requested access to the specific model family
- Confirm the region supports the selected model

### Authentication Errors

- Verify your Access Key ID and Secret Access Key are correct
- Check that the credentials are still active (not expired or rotated)
- Ensure no MFA or additional authentication is required

### Connection Errors

- Check your internet connection
- Verify AWS service endpoints are accessible
- Check for any firewall or proxy settings blocking AWS API calls

## Differences from aws_bedrock_test.py

This script differs from the existing `aws_bedrock_test.py`:

- **No Inference Profiles**: Tests only direct foundation model invocation
- **Application Patterns**: Uses the exact client creation and invocation patterns from the application
- **Better UX**: Cleaner output with formatted headers and status indicators
- **Error Handling**: More comprehensive error handling and user feedback
- **Documentation**: Better inline documentation and comments

## Related Files

- `aws_bedrock_test.py` - Original Bedrock test script (includes inference profiles)
- `src/trusted_data_agent/llm/client_factory.py` - Application's client creation logic
- `src/trusted_data_agent/llm/handler.py` - Application's LLM handler with Bedrock support

## Notes

- This script excludes inference profiles by design (tests only foundation models)
- Response parsing supports all major Bedrock model providers
- The script is safe to run and only performs read operations and a single test invocation
- No data is stored or logged beyond console output

## Support

For issues or questions:
1. Check the AWS Bedrock console for model availability
2. Review IAM permissions for your credentials
3. Consult the main application's README for Bedrock setup guidance
