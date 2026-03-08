# test_prompt_fetcher_enhanced.py
import asyncio
import pprint
from langchain_mcp_adapters.client import MultiServerMCPClient

# --- Configuration ---
# These should match the configuration of your running MCP server instance.
MCP_HOST = "127.0.0.1"
MCP_PORT = "8001"
MCP_PATH = "/mcp/"
PROMPT_TO_FETCH = "base_databaseBusinessDesc"


async def main():
    """
    Connects to the MCP server, fetches a specific prompt,
    and prints its 'arguments' attribute to the console with enhanced debugging.
    """
    print(f"--- Attempting to connect to MCP Server at http://{MCP_HOST}:{MCP_PORT}{MCP_PATH} ---")

    mcp_server_url = f"http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}"
    server_configs = {
        'teradata_mcp_server': {
            "url": mcp_server_url,
            "transport": "streamable_http"
        }
    }

    try:
        mcp_client = MultiServerMCPClient(server_configs)
        async with mcp_client.session("teradata_mcp_server") as temp_session:
            print(f"\nSuccessfully connected. Fetching prompt: '{PROMPT_TO_FETCH}'...")

            prompt_obj = await temp_session.get_prompt(name=PROMPT_TO_FETCH)

            if not prompt_obj:
                print(f"\nERROR: Prompt '{PROMPT_TO_FETCH}' not found on the server.")
                return

            print("\n--- Prompt Object Retrieved ---")

            # --- ENHANCED DEBUGGING OUTPUT ---
            print("\n[DEBUG] Printing full details of the retrieved prompt object for analysis:")
            
            # 1. Print the type of the object to understand its class
            print(f"\n1. Object Type:\n{type(prompt_obj)}")

            # 2. Print all available attributes and methods of the object
            print(f"\n2. Available Attributes (from dir()):")
            pprint.pprint(dir(prompt_obj))

            # 3. Print the full string representation of the object
            print(f"\n3. Full Object Representation:\n{prompt_obj}")
            # --- END OF ENHANCED DEBUGGING ---


            # The original check remains, but now we have more context if it fails.
            if hasattr(prompt_obj, 'arguments') and prompt_obj.arguments:
                print(f"\n✅ SUCCESS: Found arguments for prompt '{PROMPT_TO_FETCH}':")
                try:
                    args_as_dicts = [arg.model_dump() for arg in prompt_obj.arguments]
                    pprint.pprint(args_as_dicts)
                except Exception as e:
                    print("\nCould not convert arguments to dictionary format. Printing as is:")
                    print(prompt_obj.arguments)
                    print(f"(Conversion Error: {e})")

            else:
                print(f"\nINFO: Prompt '{PROMPT_TO_FETCH}' was found, but it has no 'arguments' or the list is empty.")
                print("➡️ [ANALYSIS] Please check the 'Available Attributes' and 'Full Object Representation' printed above to see if the argument data exists under a different attribute name.")

    except Exception as e:
        print(f"\n--- ❗️AN ERROR OCCURRED ---")
        print(f"Failed to connect to the MCP server or fetch the prompt.")
        print("Please ensure the MCP server is running and accessible at the configured address.")
        print(f"Error details: {e}")


if __name__ == "__main__":
    # To run this script:
    # 1. Make sure your MCP server is running.
    # 2. Run `python <filename>.py` in your terminal.
    asyncio.run(main())