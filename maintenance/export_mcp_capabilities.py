#!/usr/bin/env python3
"""
Export MCP capabilities from Teradata MCP server to prepare tda_config.json structure.
This script connects to the configured MCP server and exports all tools and prompts.
"""

import asyncio
import sys
import os
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langchain_mcp_adapters.client import MultiServerMCPClient

async def main():
    """Connect to MCP server and export all capabilities."""
    
    # Load tda_config.json to get server details
    config_path = Path(__file__).parent.parent / "tda_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Get active MCP server
    active_mcp_id = config.get('active_mcp_server_id')
    if not active_mcp_id:
        print("❌ No active MCP server configured in tda_config.json")
        return
    
    mcp_servers = config.get('mcp_servers', [])
    active_server = next((s for s in mcp_servers if s.get('id') == active_mcp_id), None)
    
    if not active_server:
        print(f"❌ Active MCP server '{active_mcp_id}' not found in configuration")
        return
    
    print(f"📡 Connecting to MCP server: {active_server['name']}")
    print(f"   Host: {active_server['host']}:{active_server['port']}")
    print(f"   Path: {active_server['path']}")
    
    # Construct server URL
    server_url = f"http://{active_server['host']}:{active_server['port']}{active_server['path']}"
    
    try:
        # Use streamable_http client to connect to HTTP MCP server
        print("\n🔌 Loading MCP capabilities...")
        
        server_name = active_server['name']
        temp_server_configs = {server_name: {"url": server_url, "transport": "streamable_http"}}
        temp_mcp_client = MultiServerMCPClient(temp_server_configs)
        
        async with temp_mcp_client.session(server_name) as session:
            # Get tools
            tools_response = await session.list_tools()
            tools = [tool.name for tool in tools_response.tools]
            
            # Get prompts
            prompts_response = await session.list_prompts()
            prompts = [prompt.name for prompt in prompts_response.prompts]
            
            print(f"\n✅ Found {len(tools)} tools and {len(prompts)} prompts\n")
            
            # Display tools
            print("📦 TOOLS:")
            for tool in sorted(tools):
                print(f"  - {tool}")
            
            print("\n📝 PROMPTS:")
            for prompt in sorted(prompts):
                print(f"  - {prompt}")
            
            # Create the structure for tda_config.json
            # Default disabled lists (these will become enabled lists by inverting them)
            default_disabled_prompts = [
                "base_query",
                "qlty_databaseQuality",
                "dba_databaseLineage",
                "base_tableBusinessDesc",
                "base_databaseBusinessDesc",
                "dba_databaseHealthAssessment",
                "dba_userActivityAnalysis",
                "dba_systemVoice",
                "dba_tableArchive",
                "dba_tableDropImpact",
                "_testMyServer"
            ]
            
            default_disabled_tools = [
                "sales_top_customers",
                "plot_line_chart",
                "plot_pie_chart",
                "plot_polar_chart",
                "plot_radar_chart",
                "sql_Analyze_Cluster_Stats",
                "rag_Execute_Workflow",
                "sql_Execute_Full_Pipeline",
                "sql_Retrieve_Cluster_Queries"
            ]
            
            # Filter to only include those that actually exist in the MCP server
            disabled_prompts_filtered = [p for p in default_disabled_prompts if p in prompts]
            disabled_tools_filtered = [t for t in default_disabled_tools if t in tools]
            
            # Calculate enabled lists (all - disabled)
            enabled_tools = sorted(list(set(tools) - set(disabled_tools_filtered)))
            enabled_prompts = sorted(list(set(prompts) - set(disabled_prompts_filtered)))
            
            print("\n" + "="*60)
            print("📋 CONFIGURATION FOR tda_config.json")
            print("="*60)
            
            # MCP Server configuration (just lists available capabilities)
            mcp_server_config = {
                "mcp_server": {
                    active_mcp_id: {
                        "all_tools": sorted(tools),
                        "all_prompts": sorted(prompts)
                    }
                }
            }
            
            # Profile configuration (lists what's enabled)
            profile_config = {
                "profile_enabled_lists": {
                    "enabled_tools": enabled_tools,
                    "enabled_prompts": enabled_prompts
                }
            }
            
            print("\n=== MCP Server Config ===")
            print(json.dumps(mcp_server_config, indent=2))
            print("\n=== Profile Config (Default Enabled Lists) ===")
            print(json.dumps(profile_config, indent=2))
            
            # Save to file
            output_path = Path(__file__).parent / "mcp_capabilities_export.json"
            export_data = {
                "mcp_server_config": mcp_server_config,
                "profile_config": profile_config
            }
            with open(output_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            print(f"\n💾 Exported to: {output_path}")
            print("\n✨ Next steps:")
            print("   1. Review the exported configuration")
            print("   2. MCP server config shows all available tools/prompts")
            print("   3. Profile config shows recommended enabled_tools/enabled_prompts for new profiles")
            print(f"   4. {len(enabled_tools)} tools and {len(enabled_prompts)} prompts are enabled by default")
        
    except Exception as e:
        print(f"\n❌ Error connecting to MCP server: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
