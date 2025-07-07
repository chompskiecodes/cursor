#!/usr/bin/env python3
"""
Ngrok ElevenLabs Call Logger
Extracts and formats ngrok inspect logs for ElevenLabs voice calls
"""

import requests
import json
from datetime import datetime
import base64
from typing import List, Dict, Any
import argparse
from urllib.parse import urlparse

NGROK_API = "http://localhost:4040/api/requests/http"
TIME_GAP_SECONDS = 240  # 4 minutes between calls

class NgrokLogExtractor:
    def __init__(self, api_url: str = NGROK_API, debug: bool = False):
        self.api_url = api_url
        self.debug = debug
        
    def fetch_requests(self) -> List[Dict[str, Any]]:
        """Fetch all requests from ngrok inspect API"""
        try:
            resp = requests.get(self.api_url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            requests_list = data.get('requests', [])
            
            if self.debug:
                print(f"DEBUG: Found {len(requests_list)} request summaries")
            
            # The list endpoint only returns summaries, we need to fetch full details
            detailed_requests = []
            for i, req_summary in enumerate(requests_list):
                req_id = req_summary.get('id')
                if req_id:
                    if self.debug and i < 3:  # Only debug first 3
                        print(f"DEBUG: Fetching details for request {req_id}")
                    
                    detailed = self.extract_request_details(req_id)
                    if detailed:
                        detailed_requests.append(detailed)
                    else:
                        # Fall back to summary if detail fetch fails
                        detailed_requests.append(req_summary)
                        
            return detailed_requests
        except requests.exceptions.ConnectionError:
            print("ERROR: Cannot connect to ngrok web interface at http://localhost:4040")
            print("\nPlease ensure:")
            print("1. ngrok is running (start with: ngrok http 8000)")
            print("2. The web interface is enabled (check http://localhost:4040 in your browser)")
            print("3. You haven't disabled the web interface in your ngrok config")
            return []
        except Exception as e:
            print(f"Error fetching from ngrok: {e}")
            return []
    
    def parse_time(self, ts: str) -> datetime:
        """Parse timestamp from ngrok format"""
        if not ts:
            return datetime.now()
        
        try:
            # Handle different formats
            if 'T' in ts:
                # ISO format - extract date and time portion
                dt_part = ts.split('.')[0].split('+')[0].split('Z')[0]
                if '-' in dt_part and dt_part.count('-') > 2:
                    # Handle timezone in format
                    dt_part = dt_part.rsplit('-', 1)[0]
                return datetime.fromisoformat(dt_part)
            return datetime.now()
        except:
            return datetime.now()
    
    def decode_body(self, body_data: Any) -> str:
        """Decode request/response body from base64"""
        if not body_data:
            return ""
        
        # Check if it's the raw base64 string
        if isinstance(body_data, str):
            try:
                # Decode base64
                decoded = base64.b64decode(body_data)
                text = decoded.decode('utf-8')
                
                # Try to parse as JSON for pretty printing
                try:
                    obj = json.loads(text)
                    return json.dumps(obj, indent=2)
                except:
                    return text
            except:
                return body_data
        
        return str(body_data)
    
    def extract_request_details(self, req_id: str) -> Dict[str, Any]:
        """Fetch detailed request data for a specific request ID"""
        try:
            # Fetch detailed data for this request
            detail_url = f"{self.api_url}/{req_id}"
            resp = requests.get(detail_url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            
            if self.debug:
                print(f"\nDEBUG: Request {req_id} details:")
                print(f"URI: {data.get('uri', 'N/A')}")
                print(f"Has request data: {'request' in data}")
                print(f"Has response data: {'response' in data}")
            
            return data
        except requests.exceptions.ConnectionError:
            if self.debug:
                print(f"Connection error for request {req_id}")
            return {}
        except Exception as e:
            if self.debug:
                print(f"Error fetching request details for {req_id}: {e}")
            return {}
    
    def extract_tool_info(self, req: Dict) -> Dict[str, Any]:
        """Extract tool call information from request"""
        info = {
            'endpoint': '',
            'tool_name': '',
            'params': {},
            'response_status': '',
            'response_data': {},
            'method': req.get('method', 'GET'),
            'headers': {},
            'request_body': '',
            'response_body': ''
        }
        
        # Get URI and extract endpoint
        uri = req.get('uri', '')
        if uri:
            try:
                # Parse the full URL
                parsed = urlparse(uri)
                info['endpoint'] = parsed.path
                
                # Extract tool name from path
                if parsed.path and parsed.path != '/':
                    # Remove leading slash and convert to tool name
                    tool_name = parsed.path.strip('/').replace('-', '_')
                    info['tool_name'] = tool_name
            except:
                # Fallback
                info['endpoint'] = uri
                info['tool_name'] = uri.split('/')[-1].replace('-', '_')
        
        # Get request details
        request_data = req.get('request', {})
        if request_data:
            info['method'] = request_data.get('method', 'GET')
            info['headers'] = request_data.get('headers', {})
            
            # Decode request body
            raw_body = request_data.get('raw', '')
            if raw_body:
                info['request_body'] = self.decode_body(raw_body)
                try:
                    info['params'] = json.loads(info['request_body'])
                except:
                    info['params'] = info['request_body']
        
        # Get response details
        response_data = req.get('response', {})
        if response_data:
            status_code = response_data.get('status_code', '')
            status_text = response_data.get('status', '')
            info['response_status'] = f"{status_code} {status_text}".strip()
            
            # Decode response body
            raw_body = response_data.get('raw', '')
            if raw_body:
                info['response_body'] = self.decode_body(raw_body)
                try:
                    info['response_data'] = json.loads(info['response_body'])
                except:
                    info['response_data'] = info['response_body']
        
        return info
    
    def group_by_call(self, requests: List[Dict]) -> List[List[Dict]]:
        """Group requests by ElevenLabs call sessions"""
        if not requests:
            return []
        
        # Sort by timestamp
        sorted_reqs = sorted(requests, key=lambda r: self.parse_time(r.get('start', '')))
        
        groups = []
        current_group = []
        last_time = None
        
        for req in sorted_reqs:
            req_time = self.parse_time(req.get('start', ''))
            
            # Check if this is a new call group
            if last_time and (req_time - last_time).total_seconds() > TIME_GAP_SECONDS:
                if current_group:
                    groups.append(current_group)
                current_group = []
            
            current_group.append(req)
            last_time = req_time
        
        if current_group:
            groups.append(current_group)
        
        return groups
    
    def format_call_summary(self, call_group: List[Dict]) -> str:
        """Format a call group as a summary"""
        if not call_group:
            return "Empty call group"
        
        output = []
        start_time = self.parse_time(call_group[0].get('start', ''))
        output.append(f"\n{'='*80}")
        output.append(f"ELEVENLABS CALL SESSION - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"Total requests: {len(call_group)}")
        output.append(f"{'='*80}\n")
        
        for i, req in enumerate(call_group, 1):
            tool_info = self.extract_tool_info(req)
            
            output.append(f"[{i}] {tool_info['tool_name'] or 'Unknown Tool'}")
            output.append(f"    Endpoint: {tool_info['endpoint']}")
            output.append(f"    Status: {tool_info['response_status']}")
            
            # Show key parameters
            if isinstance(tool_info['params'], dict):
                key_params = []
                params = tool_info['params']
                
                # Common parameters to show
                param_map = {
                    'practitioner': 'practitioner',
                    'service': 'service',
                    'business_id': 'business_id',
                    'locationQuery': 'location',
                    'patientName': 'patient',
                    'userResponse': 'response',
                    'appointmentType': 'service',
                    'appointmentDate': 'date',
                    'appointmentTime': 'time'
                }
                
                for param_key, display_name in param_map.items():
                    if param_key in params:
                        value = params[param_key]
                        key_params.append(f"{display_name}='{value}'")
                
                if key_params:
                    output.append(f"    Params: {', '.join(key_params)}")
            
            # Show key response data
            if isinstance(tool_info['response_data'], dict):
                resp = tool_info['response_data']
                
                if resp.get('success') == False:
                    output.append(f"    ❌ ERROR: {resp.get('message', 'Unknown error')}")
                elif resp.get('business_id'):
                    output.append(f"    ✓ Resolved to: {resp.get('business_name')} ({resp.get('business_id')})")
                elif resp.get('location_confirmed'):
                    output.append(f"    ✓ Location confirmed: {resp.get('location_name')}")
                elif resp.get('found'):
                    output.append(f"    ✓ Found: {resp.get('message', '')}")
                elif resp.get('appointmentDetails'):
                    details = resp['appointmentDetails']
                    output.append(f"    ✓ BOOKED: {details}")
                elif 'message' in resp:
                    output.append(f"    Response: {resp['message'][:100]}...")
            
            output.append("")
        
        return "\n".join(output)
    
    def format_call_detailed(self, call_group: List[Dict]) -> str:
        """Format a call group with full details"""
        if not call_group:
            return "Empty call group"
        
        output = []
        start_time = self.parse_time(call_group[0].get('start', ''))
        output.append(f"\n{'='*80}")
        output.append(f"DETAILED CALL LOG - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"{'='*80}\n")
        
        for i, req in enumerate(call_group, 1):
            tool_info = self.extract_tool_info(req)
            
            output.append(f"\n{'-'*60}")
            output.append(f"REQUEST #{i} - {tool_info['tool_name']}")
            output.append(f"{'-'*60}")
            
            # Request details
            output.append(f"Time: {req.get('start', 'N/A')}")
            output.append(f"Method: {tool_info['method']}")
            output.append(f"URI: {req.get('uri', 'N/A')}")
            output.append(f"Endpoint: {tool_info['endpoint']}")
            
            # Request headers (excluding sensitive data)
            if tool_info['headers']:
                output.append("\nRequest Headers:")
                for k, v in tool_info['headers'].items():
                    if k.lower() not in ['x-api-key', 'authorization']:
                        output.append(f"  {k}: {v}")
            
            # Request body
            if tool_info['request_body']:
                output.append("\nRequest Body:")
                output.append(tool_info['request_body'])
            
            # Response
            output.append(f"\nResponse Status: {tool_info['response_status']}")
            
            # Response body
            if tool_info['response_body']:
                output.append("\nResponse Body:")
                output.append(tool_info['response_body'])
        
        return "\n".join(output)
    
    def export_markdown(self, call_groups: List[List[Dict]], num_calls: int = 1) -> str:
        """Export calls as markdown for easy sharing"""
        output = []
        output.append("# ElevenLabs Voice Call Logs\n")
        
        # Get the most recent calls
        recent_groups = call_groups[-num_calls:] if len(call_groups) >= num_calls else call_groups
        
        for i, group in enumerate(recent_groups, 1):
            start_time = self.parse_time(group[0].get('start', ''))
            output.append(f"## Call {i} - {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            output.append("### Tool Calls Summary\n")
            output.append("```")
            
            for j, req in enumerate(group, 1):
                tool_info = self.extract_tool_info(req)
                output.append(f"{j}. {tool_info['tool_name']} → {tool_info['response_status']}")
            
            output.append("```\n")
            
            output.append("### Detailed Requests\n")
            
            for j, req in enumerate(group, 1):
                tool_info = self.extract_tool_info(req)
                
                output.append(f"#### {j}. {tool_info['tool_name']}\n")
                
                output.append("**Request:**")
                output.append("```json")
                if isinstance(tool_info['params'], dict):
                    output.append(json.dumps(tool_info['params'], indent=2))
                else:
                    output.append(str(tool_info['params']))
                output.append("```\n")
                
                output.append("**Response:**")
                output.append("```json")
                if isinstance(tool_info['response_data'], dict):
                    output.append(json.dumps(tool_info['response_data'], indent=2))
                else:
                    output.append(str(tool_info['response_data']))
                output.append("```\n")
        
        return "\n".join(output)

def main():
    parser = argparse.ArgumentParser(description='Extract ElevenLabs calls from ngrok logs')
    parser.add_argument('-n', '--num-calls', type=int, default=1, help='Number of recent calls to show')
    parser.add_argument('-d', '--detailed', action='store_true', help='Show detailed output')
    parser.add_argument('-m', '--markdown', action='store_true', help='Export as markdown')
    parser.add_argument('-a', '--all', action='store_true', help='Show all calls, not just recent')
    parser.add_argument('--debug', action='store_true', help='Show debug information')
    parser.add_argument('--api-url', default=NGROK_API, help='Override ngrok API URL')
    
    args = parser.parse_args()
    
    # Check if ngrok is accessible
    try:
        test_resp = requests.get("http://localhost:4040", timeout=2)
        if args.debug:
            print(f"DEBUG: ngrok web interface is accessible")
    except:
        print("WARNING: Cannot access ngrok web interface at http://localhost:4040")
        print("\nMake sure ngrok is running. Start it with:")
        print("  ngrok http 8000")
        print("\nOr if you're using a different port:")
        print("  ngrok http YOUR_PORT")
        print("\nIf ngrok is running on a different address, use --api-url flag:")
        print("  python import_requests.py --api-url http://YOUR_ADDRESS:4040/api/requests/http")
        return
    
    extractor = NgrokLogExtractor(api_url=args.api_url, debug=args.debug)
    
    print("Fetching ngrok requests...")
    requests = extractor.fetch_requests()
    
    if not requests:
        print("No requests found. Make sure ngrok is running and has captured some traffic.")
        print("The web interface should be accessible at http://localhost:4040")
        return
    
    print(f"Found {len(requests)} total requests with details")
    
    # Group by call
    call_groups = extractor.group_by_call(requests)
    print(f"Grouped into {len(call_groups)} call sessions")
    
    if not call_groups:
        print("No call groups found.")
        return
    
    # Determine which calls to show
    if args.all:
        groups_to_show = call_groups
    else:
        groups_to_show = call_groups[-args.num_calls:]
    
    # Output based on format
    if args.markdown:
        print(extractor.export_markdown(call_groups, args.num_calls))
    elif args.detailed:
        for group in groups_to_show:
            print(extractor.format_call_detailed(group))
    else:
        for group in groups_to_show:
            print(extractor.format_call_summary(group))

if __name__ == "__main__":
    main()