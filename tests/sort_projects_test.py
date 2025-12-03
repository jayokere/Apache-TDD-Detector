import pytest
import sys
import json
from unittest.mock import MagicMock

# 1. Mock internal modules so the test runs without 'miner_intro' existing
sys.modules["miner_intro"] = MagicMock()

# Now import the class to be tested
from sort_projects import sort_projects

class FakeResponse:
    def __init__(self, json_data, headers=None, status_code=200):
        self._json_data = json_data
        self.headers = headers if headers else {}
        self.status_code = status_code

    def json(self):
        return self._json_data

class FakeFile:
    def __init__(self):
        self.content = None

    def write(self, data):
        self.content = data
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def test_get_commit_count_uses_pagination_header(monkeypatch):
    """
    Test that if a Link header is present, the commit count is extracted 
    from the 'last' page parameter.
    """
    
    # Prepare a fake response with pagination
    fake_headers = {
        'Link': '<https://api.github.com/repositories/123/commits?per_page=1&page=500>; rel="last"'
    }
    fake_resp = FakeResponse(json_data=[], headers=fake_headers)

    # Patch requests.get to return our fake response
    monkeypatch.setattr("requests.get", lambda url, headers, timeout: fake_resp)

    sorter = sort_projects()
    # We bypass __init__ file loading by manually ensuring api_err is ready if needed
    sorter.API_err = []
    
    count = sorter.get_commit_count("https://github.com/apache/active-repo")
    
    assert count == 500

def test_get_commit_count_counts_list_items(monkeypatch):
    """
    Test that if no Link header is present, the method counts the 
    number of items in the JSON list.
    """
    # Prepare a fake response list of 3 items
    fake_data = [{}, {}, {}] 
    fake_resp = FakeResponse(json_data=fake_data, headers={})

    monkeypatch.setattr("requests.get", lambda url, headers, timeout: fake_resp)

    sorter = sort_projects()
    count = sorter.get_commit_count("https://github.com/apache/small-repo")

    assert count == 3

def test_get_commit_count_handles_api_failure(monkeypatch):
    """
    Test that a 404 or other non-200 status code logs an error 
    and (based on your current logic) returns 0 or list length.
    """
    # Prepare a fake 404 response
    fake_resp = FakeResponse(json_data=[], status_code=404)

    monkeypatch.setattr("requests.get", lambda url, headers, timeout: fake_resp)

    sorter = sort_projects()
    sorter.API_err = []

    # Note: In your current code, a 404 falls through to len(response.json())
    # which is 0 for our empty list.
    count = sorter.get_commit_count("https://github.com/apache/missing-repo")

    assert count == 0
    assert len(sorter.API_err) == 1
    assert "404" in sorter.API_err[0]

def test_sort_by_commit_count_orders_correctly(monkeypatch):
    """
    Test that the projects are sorted in descending order based on commit counts,
    and the file writing is triggered.
    """
    
    # 1. Setup the initial unsorted data
    initial_data = {
        "Project_Low": ["https://github.com/apache/low"],
        "Project_High": ["https://github.com/apache/high"],
        "Project_Med": ["https://github.com/apache/med"]
    }

    # 2. Create the sorter and inject data manually to avoid file I/O in __init__
    sorter = sort_projects()
    sorter.apache_projects = initial_data

    # 3. Define a fake get_commit_count that returns specific values based on URL
    def fake_get_commit_count(self, url):
        if "high" in url: return 100
        if "med" in url: return 50
        if "low" in url: return 10
        return 0

    # Patch the method on the class. 
    # Note: We patch the method on the class or instance. 
    # Since we are calling it via self.get_commit_count, we can patch the instance method.
    monkeypatch.setattr(sorter, "get_commit_count", fake_get_commit_count.__get__(sorter, sort_projects))

    # 4. Patch json.dump to capture what would be written to file
    fake_file = FakeFile()
    captured_output = {}

    def fake_dump(obj, fp, indent=4):
        nonlocal captured_output
        captured_output = obj
    
    monkeypatch.setattr("json.dump", fake_dump)
    monkeypatch.setattr("builtins.open", lambda path, mode, encoding: fake_file)

    # 5. Run the sort
    result_len = sorter.sort_by_commit_count()

    # 6. Assertions
    assert result_len == 3
    
    # Check keys order in the captured output
    # Note: Python 3.7+ preserves insertion order, so we can check the keys list
    keys = list(captured_output.keys())
    
    assert keys[0] == "Project_High"  # 100 commits
    assert keys[1] == "Project_Med"   # 50 commits
    assert keys[2] == "Project_Low"   # 10 commits