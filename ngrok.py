#!/usr/bin/env python3
"""
ngrok Inspection Logs Fetcher - Enhanced Version
Fetches and decodes the full HTTP request/response data from ngrok's local inspection interface
"""

import requests
import json
import base64
from datetime import datetime, timedelta
import argparse
import sys
import os

class NgrokInspector:
    def __init__(self, base_url="http://127.0.0.1:4040"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
    
    def check_ngrok_running(self):
        """Check if ngrok is running and accessible"""
        try:
            response = requests.get(f"{self.api_url}/status", timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def get_tunnels(self):
        """Get list of active tunnels"""
        try:
            response = requests.get(f"{self.api_url}/tunnels")
            response.raise_for_status()
            return response.json().get('tunnels', [])
        except requests.exceptions.RequestException as e:
            print(f"Error fetching tunnels: {e}")
            return []
    
    def get_requests(self, limit=None, tunnel_name=None):
        """Get captured HTTP requests"""
        params = {}
        if limit:
            params['limit'] = limit
        if tunnel_name:
            params['tunnel_name'] = tunnel_name
        
        try:
            response = requests.get(f"{self.api_url}/requests/http", params=params)
            response.raise_for_status()
            return response.json().get('requests', [])
        except requests.exceptions.RequestException as e:
            print(f"Error fetching requests: {e}")
            return []
    
    def get_request_detail(self, request_id):
        """Get detailed information about a specific request"""
        try:
            response = requests.get(f"{self.api_url}/requests/http/{request_id}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching request detail for {request_id}: {e}")
            return None
    
    def decode_raw_data(self, base64_data):
        """Decode base64 encoded raw HTTP data"""
        if not base64_data:
            return ""
        try:
            decoded_bytes = base64.b64decode(base64_data)
            # Try to decode as UTF-8, fallback to latin-1 if needed
            try:
                return decoded_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return decoded_bytes.decode('latin-1')
        except Exception as e:
            print(f"Error decoding data: {e}")
            return f"[Error decoding data: {e}]"
    
    def format_request_full(self, request_data, detail_data):
        """Format complete request/response information"""
        output = []
        
        # Header with timestamp
        timestamp = datetime.fromisoformat(request_data['start'].replace('Z', '+00:00'))
        formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        output.append(f"{'='*80}")
        output.append(f"Request Time: {formatted_time}")
        output.append(f"Request ID: {request_data['id']}")
        output.append(f"Duration: {request_data.get('duration', 0) / 1000000:.2f}ms")
        output.append(f"{'='*80}")
        
        # Request section
        if detail_data and 'request' in detail_data:
            req_detail = detail_data['request']
            
            # Decode and show raw request
            if 'raw' in req_detail:
                output.append("\n--- REQUEST ---")
                raw_request = self.decode_raw_data(req_detail['raw'])
                output.append(raw_request)
        
        # Response section
        if detail_data and 'response' in detail_data:
            resp_detail = detail_data['response']
            
            # Decode and show raw response
            if 'raw' in resp_detail:
                output.append("\n--- RESPONSE ---")
                raw_response = self.decode_raw_data(resp_detail['raw'])
                output.append(raw_response)
        
        output.append(f"\n{'='*80}\n")
        return '\n'.join(output)
    
    def save_requests_to_file(self, requests, filename, detailed=True):
        """Save requests to a file with full details"""
        content = []
        content.append(f"ngrok Request Logs - Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content.append(f"Total Requests: {len(requests)}\n")
        
        for i, req in enumerate(requests, 1):
            print(f"Processing request {i}/{len(requests)}...", end='\r')
            
            if detailed:
                # Fetch detailed information for each request
                detail = self.get_request_detail(req['id'])
                if detail:
                    content.append(self.format_request_full(req, detail))
                else:
                    # Fallback to basic info if detail fetch fails
                    timestamp = datetime.fromisoformat(req['start'].replace('Z', '+00:00'))
                    formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    content.append(f"{formatted_time} | {req.get('method', 'UNKNOWN')} | {req.get('uri', 'N/A')}")
            else:
                # Basic format
                timestamp = datetime.fromisoformat(req['start'].replace('Z', '+00:00'))
                formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                method = req.get('method', 'UNKNOWN')
                uri = req.get('uri', '')
                status = req.get('response', {}).get('status', 'pending')
                duration = req.get('duration', 0) / 1000000
                content.append(f"{formatted_time} | {method:6} | {status:3} | {duration:7.2f}ms | {uri}")
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
        
        print(f"\nSaved {len(requests)} requests to {filename}")
    
    def display_requests(self, requests, detailed=False):
        """Display requests in console"""
        if not requests:
            print("No requests captured yet.")
            return
        
        print(f"\n{'='*80}")
        print(f"Most Recent HTTP Requests (Total: {len(requests)})")
        print(f"{'='*80}")
        
        if detailed:
            for req in requests[:5]:  # Limit console output for detailed view
                detail = self.get_request_detail(req['id'])
                if detail:
                    print(self.format_request_full(req, detail))
            if len(requests) > 5:
                print(f"\nShowing first 5 of {len(requests)} requests. Use --output to save all to file.")
        else:
            print(f"{'Timestamp':19} | {'Method':6} | {'Status':3} | {'Duration':>9} | URL")
            print(f"{'-'*80}")
            for req in requests:
                timestamp = datetime.fromisoformat(req['start'].replace('Z', '+00:00'))
                formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                method = req.get('method', 'UNKNOWN')
                uri = req.get('uri', '')
                status = req.get('response', {}).get('status', 'pending')
                duration = req.get('duration', 0) / 1000000
                print(f"{formatted_time} | {method:6} | {status:3} | {duration:7.2f}ms | {uri}")
    
    def watch_requests(self, interval=2, limit=10):
        """Continuously watch for new requests"""
        import time
        
        seen_ids = set()
        
        print("Watching for new requests... (Press Ctrl+C to stop)")
        
        try:
            while True:
                requests = self.get_requests(limit=limit)
                new_requests = [r for r in requests if r['id'] not in seen_ids]
                
                if new_requests:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] New requests detected:")
                    for req in new_requests:
                        timestamp = datetime.fromisoformat(req['start'].replace('Z', '+00:00'))
                        formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                        method = req.get('method', 'UNKNOWN')
                        uri = req.get('uri', '')
                        status = req.get('response', {}).get('status', 'pending')
                        duration = req.get('duration', 0) / 1000000
                        print(f"  {formatted_time} | {method:6} | {status:3} | {duration:7.2f}ms | {uri}")
                        seen_ids.add(req['id'])
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\nStopped watching.")

def filter_recent_requests(requests, max_gap_seconds=120):
    """Return the most recent consecutive requests with ≤ max_gap_seconds between them."""
    if not requests:
        return []
    # Sort requests by start time descending (most recent first)
    sorted_requests = sorted(requests, key=lambda r: r['start'], reverse=True)
    filtered = [sorted_requests[0]]
    last_time = datetime.fromisoformat(sorted_requests[0]['start'].replace('Z', '+00:00'))
    for req in sorted_requests[1:]:
        this_time = datetime.fromisoformat(req['start'].replace('Z', '+00:00'))
        gap = (last_time - this_time).total_seconds()
        if gap > max_gap_seconds:
            break
        filtered.append(req)
        last_time = this_time
    return filtered

def main():
    parser = argparse.ArgumentParser(description='Fetch and display ngrok inspection logs with full details')
    parser.add_argument('-l', '--limit', type=int, help='Limit number of requests to fetch')
    parser.add_argument('-t', '--tunnel', help='Filter by tunnel name')
    parser.add_argument('-w', '--watch', action='store_true', help='Watch for new requests continuously')
    parser.add_argument('--basic', action='store_true', help='Save only basic info when using --output')
    parser.add_argument('--url', default='http://127.0.0.1:4040', help='ngrok web interface URL (default: http://127.0.0.1:4040)')
    parser.add_argument('--tunnels', action='store_true', help='List active tunnels')
    
    args = parser.parse_args()
    
    inspector = NgrokInspector(base_url=args.url)
    
    # Check if ngrok is running
    if not inspector.check_ngrok_running():
        print(f"Error: Cannot connect to ngrok at {args.url}")
        print("Make sure ngrok is running and the web interface is accessible.")
        sys.exit(1)
    
    # List tunnels if requested
    if args.tunnels:
        tunnels = inspector.get_tunnels()
        if tunnels:
            print("\nActive Tunnels:")
            for tunnel in tunnels:
                print(f"  - {tunnel['name']}: {tunnel['public_url']} -> {tunnel['config']['addr']}")
        else:
            print("No active tunnels found.")
        print()
    
    # Watch mode
    if args.watch:
        inspector.watch_requests(limit=args.limit or 10)
    else:
        detailed = True
        os.makedirs('grok', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"grok/ngrok_requests_{timestamp}.log"
        
        # Fetch requests
        requests = inspector.get_requests(limit=args.limit, tunnel_name=args.tunnel)
        
        # Filter to only most recent consecutive requests within 120s of each other
        filtered_requests = filter_recent_requests(requests, max_gap_seconds=120)
        
        # Save to file (always)
        inspector.save_requests_to_file(
            filtered_requests, 
            output_filename, 
            detailed=detailed
        )
        
        # Do not display logs in terminal, just print file created message
        print(f"File created: {output_filename}")

if __name__ == "__main__":
    main()