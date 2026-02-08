from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging

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

        elif self.path == '/api/agent/credentials':
            self._set_headers()
            response = {
                "success": True,
                "count": 1,
                "data": [
                    {
                        "id": 1,
                        "project_name": "ERP System",
                        "service_name": "Database",
                        "username": "admin",
                        "password": "decrypted-password-here",
                        "description": "Production DB Access"
                    }
                ]
            }
            self.wfile.write(json.dumps(response).encode())

        elif self.path.startswith('/api/agent/customers/') and self.path.endswith('/invoices'):
            self._set_headers()
            response = {
                "success": True,
                "customer_id": "1",
                "count": 1,
                "data": [
                     {
                        "id": 101,
                        "invoice_no": "INV-2023-001",
                        "grand_total": 5000.00,
                        "status": "Pending"
                    }
                ]
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
