#!/usr/bin/env python3
"""Test script for Bedrock Home Assistant Agent."""

import os
import sys
import json
import boto3
from botocore.exceptions import ClientError


def test_bedrock_connection():
    """Test connection to AWS Bedrock."""
    print("Testing AWS Bedrock Connection...")
    print("-" * 50)
    
    # Get configuration
    region = os.getenv('AWS_REGION', 'us-east-1')
    model_id = os.getenv('MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
    
    print(f"Region: {region}")
    print(f"Model ID: {model_id}")
    print()
    
    try:
        # Initialize Bedrock client
        bedrock_runtime = boto3.client(
            service_name='bedrock-runtime',
            region_name=region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        )
        
        print("✓ Successfully created Bedrock client")
        
        # Test prompt
        test_prompt = "Hello, can you hear me? Please respond with 'Yes, I can hear you!'"
        
        # Prepare request
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "temperature": 0.7,
            "messages": [
                {
                    "role": "user",
                    "content": test_prompt
                }
            ]
        }
        
        print(f"\nSending test prompt: {test_prompt}")
        print()
        
        # Invoke model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=json.dumps(body)
        )
        
        response_body = json.loads(response['body'].read())
        response_text = response_body['content'][0]['text']
        
        print("✓ Successfully received response from Bedrock")
        print()
        print("Response:")
        print("-" * 50)
        print(response_text)
        print("-" * 50)
        print()
        print("✓ All tests passed!")
        
        return True
        
    except ClientError as e:
        print(f"✗ AWS Error: {e}")
        print()
        print("Common issues:")
        print("- Check AWS credentials are correct")
        print("- Verify model access is enabled in Bedrock console")
        print("- Ensure the model ID is correct for your region")
        print("- Check IAM permissions include bedrock:InvokeModel")
        return False
        
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


if __name__ == '__main__':
    # Check for required environment variables
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print()
        print("Usage:")
        print("  export AWS_REGION=us-east-1")
        print("  export AWS_ACCESS_KEY_ID=your_access_key")
        print("  export AWS_SECRET_ACCESS_KEY=your_secret_key")
        print("  export MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0")
        print("  python3 test_bedrock.py")
        sys.exit(1)
    
    success = test_bedrock_connection()
    sys.exit(0 if success else 1)
