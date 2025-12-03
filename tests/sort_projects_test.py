import pytest
import sys
import json
from unittest.mock import MagicMock, patch

# Mock 'miner_intro' BEFORE importing the class
# This prevents the test from trying to print progress bars to the console.
sys.modules["miner_intro"] = MagicMock()

# Now import the class
from sort_projects import sort_projects, RateLimitExceededError

# --- Fixtures ---

@pytest.fixture
def sorter():
    """
    Creates a sorter instance with empty data.
    We patch 'open' and 'json.load' to avoid reading the real file.
    """
    with patch("builtins.open"), patch("json.load", return_value={}):
        return sort_projects()

# --- Tests for get_commit_count ---

@patch('requests.get')
def test_get_commit_count_pagination(mock_get, sorter):
    """Test that Link header pagination works."""
    # Setup response
    mock_response = MagicMock()
    mock_response.status_code = 200
    # FIX 1: Use '&page=500' because the code appends '?per_page=1' first.
    mock_response.headers = {
        'Link': '<https://api.github.com/resource?per_page=1&page=500>; rel="last"'
    }
    mock_get.return_value = mock_response

    with patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'}):
        count = sorter.get_commit_count("https://github.com/apache/test")
    
    assert count == 500

@patch('requests.get')
def test_get_commit_count_list_length(mock_get, sorter):
    """Test that list length is used if no pagination header exists."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.json.return_value = [1, 2, 3]
    mock_get.return_value = mock_response

    with patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'}):
        count = sorter.get_commit_count("https://github.com/apache/test")

    assert count == 3

@patch('requests.get')
def test_get_commit_count_returns_negative_on_error(mock_get, sorter):
    """Test that a 404 error returns -404."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {}
    mock_get.return_value = mock_response

    with patch.dict('os.environ', {'GITHUB_TOKEN': 'fake_token'}):
        count = sorter.get_commit_count("https://github.com/apache/missing")

    assert count == -404

# --- Tests for sort_by_commit_count (Multi-threading Logic) ---

def test_sort_by_commit_count_integration(sorter):
    """
    Test that the sorting logic works. 
    Crucially, we MOCK the ThreadPool and miner_intro explicitly.
    """
    # 1. Setup Mock Data
    sorter.apache_projects = {
        "Project_High": ["link1"],
        "Project_Low": ["link2"],
        "Project_Err": ["link3"]
    }

    # 2. Define fake worker results: (name, links, count, errors)
    mock_worker_results = [
        ("Project_Low", ["link2"], 5, []),
        ("Project_High", ["link1"], 100, []),
        ("Project_Err", ["link3"], 0, ["⚠️ API Error 404"])
    ]

    # This ensures we use a Mock even if the real module was already loaded.
    with patch("sort_projects.miner_intro") as mock_miner:
        
        # Patch ThreadPool where it is IMPORTED
        with patch("sort_projects.ThreadPool") as MockPool:
            pool_instance = MockPool.return_value
            # Make imap_unordered return our fake list immediately
            pool_instance.imap_unordered.return_value = mock_worker_results

            # Patch file writing
            with patch("builtins.open", new_callable=MagicMock) as mock_file:
                with patch("json.dump") as mock_dump:
                    
                    # EXECUTE
                    total_processed = sorter.sort_by_commit_count()

                    # ASSERTIONS
                    # 1. Check we processed all 3 items (assert 3 == 3)
                    assert total_processed == 3
                    
                    # 2. Check that errors were collected correctly
                    assert len(sorter.API_err) == 1
                    assert "404" in sorter.API_err[0]

                    # 3. Check the order of keys passed to json.dump
                    # Should be High (100) -> Low (5) -> Err (0)
                    args, _ = mock_dump.call_args
                    saved_dict = args[0]
                    saved_keys = list(saved_dict.keys())
                    
                    assert saved_keys == ["Project_High", "Project_Low", "Project_Err"]