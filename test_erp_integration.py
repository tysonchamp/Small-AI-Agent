import unittest
import os
import sys
import logging

# Set env vars for testing BEFORE importing config/erp_client
os.environ['GBYTE_ERP_URL'] = 'http://127.0.0.1:8001' # Testing auto-append logic
os.environ['AI_AGENT_API_KEY'] = 'secret-agent-key'

# Mock config.load_config to enforce these values even if config.yaml exists
import config
original_load_config = config.load_config

def mock_load_config():
    conf = original_load_config() or {}
    conf['GBYTE_ERP_URL'] = os.environ['GBYTE_ERP_URL']
    conf['API_KEY'] = os.environ['AI_AGENT_API_KEY']
    return conf

config.load_config = mock_load_config

import erp_client

class TestERPIntegration(unittest.TestCase):
    def test_get_pending_tasks(self):
        print("\nTesting get_pending_tasks...")
        result = erp_client.get_pending_tasks()
        print(result)
        self.assertIn("Fix Login Bug", result)

    def test_get_due_invoices(self):
        print("\nTesting get_due_invoices...")
        result = erp_client.get_due_invoices()
        print(result)
        self.assertIn("INV-2023-001", result)

    def test_get_invoice_summary(self):
        print("\nTesting get_invoice_summary...")
        result = erp_client.get_invoice_summary()
        print(result)
        self.assertIn("Total Pending Amount: 15000.0", result)

    def test_get_credentials(self):
        print("\nTesting get_credentials...")
        result = erp_client.get_credentials()
        print(result)
        self.assertIn("ERP System", result)

    def test_get_customer_invoices(self):
        print("\nTesting get_customer_invoices...")
        result = erp_client.get_customer_invoices(1)
        print(result)
        self.assertIn("INV-2023-001", result)

if __name__ == '__main__':
    unittest.main()
