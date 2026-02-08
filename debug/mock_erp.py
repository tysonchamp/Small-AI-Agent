from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
import json
import logging
import sys
import os

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logging
logging.basicConfig(level=logging.INFO)

API_KEY = "secret-agent-key"

class MockERPServer(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def do_GET(self):
        # Check API Key
        api_key = self.headers.get('X-API-KEY')
        if api_key != API_KEY:
            self._set_headers(401)
            self.wfile.write(json.dumps({"success": False, "message": "Unauthorized"}).encode())
            return

        if self.path == '/api/agent/tasks/pending':
            self._set_headers()
            response = {
                "success": True,
                "count": 1,
                "data": [
                    {
                        "id": 1,
                        "title": "Fix Login Bug",
                        "status": "in_progress",
                        "priority": "high",
                        "due_date": "2023-12-31",
                        "type": "bug",
                        "assignees": ["John Doe"],
                        "sub_tasks": [
                            {
                                "id": 10,
                                "title": "Check AuthController",
                                "status": "todo",
                                "priority": "medium"
                            }
                        ]
                    }
                ]
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path == '/api/agent/invoices/due':
            self._set_headers()
            response = {
                "success": True,
                "count": 1,
                "data": [
                    {
                        "id": 101,
                        "invoice_no": "INV-2023-001",
                        "customer_name": "Acme Corp",
                        "date": "2023-11-01",
                        "grand_total": 5000.00,
                        "paid_amount": 1000.00,
                        "due_amount": 4000.00,
                        "status": "Pending"
                    }
                ]
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path == '/api/agent/invoices/summary':
            self._set_headers()
            response = {
                "success": True,
                "summary": {
                    "total_pending_amount": 15000.00,
                    "pending_invoices_count": 5,
                    "total_invoiced_amount": 50000.00
                }
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path.startswith('/api/agent/credentials'):
            from urllib.parse import urlparse, parse_qs
            query_components = parse_qs(urlparse(self.path).query)
            search = query_components.get('search', [None])[0]

            self._set_headers()
            
            # Simple mock filter
            if search and search.lower() not in "cloud project vps server":
                 response = {
                    "success": True,
                    "count": 0,
                    "data": []
                }
            else:
                response = {
                    "success": True,
                    "count": 1,
                    "data": [
                        {
                            "id": 1,
                            "project_name": "Cloud Project",
                            "service_name": "VPS Server",
                            "username": "root",
                            "password": "decrypted-password-here",
                            "description": "Production VPS"
                        }
                    ]
                }
            self.wfile.write(json.dumps(response).encode())

        elif self.path.startswith('/api/agent/customers/') and self.path.endswith('/invoices'):
            self._set_headers()
            try:
                # Extract customer ID from URL
                parts = self.path.split('/')
                customer_id = parts[-2]
                
                # ... fetch by ID logic ...
                # Use query param or path? Path as per doc: /customers/{id}/invoices
                
                # MOCK DATA
                response = {
                    "success": True,
                    "customer_id": customer_id,
                    "count": 1,
                    "data": [
                         {
                            "id": 101,
                            "invoice_no": f"INV-2023-{customer_id}",
                            "customer_name": f"Customer {customer_id}",
                            "grand_total": 5000.00,
                            "status": "Pending"
                        }
                    ]
                }
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode())

        elif self.path.startswith('/api/agent/invoices') and '/customers/' not in self.path:
             # Search Invoices
            from urllib.parse import urlparse, parse_qs
            query_components = parse_qs(urlparse(self.path).query)
            customer_name = query_components.get('customer_name', [None])[0]
            
            self._set_headers()
            if customer_name and "John" in customer_name:
                 response = {
                    "success": True,
                    "count": 1,
                     "data": [
                        {
                            "id": 105,
                            "invoice_no": "INV-2023-005",
                            "customer_name": "John Doe",
                            "date": "2023-11-20",
                            "grand_total": 1500.00,
                            "paid_amount": 0,
                            "due_amount": 1500.00,
                            "status": "Pending"
                        }
                    ]
                }
            else:
                 response = {
                    "success": True,
                    "count": 0,
                    "data": []
                }
            self.wfile.write(json.dumps(response).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"success": False, "message": "Not Found"}).encode())

def run(server_class=HTTPServer, handler_class=MockERPServer, port=8001):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    logging.info(f"Starting mock ERP server on port {port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    run()
