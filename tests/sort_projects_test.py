import pytest
import json
import sys
from unittest.mock import MagicMock, patch, mock_open

# -------------------------------------------------------------------------
# 1. Mock Internal Modules
# BEFORE importing sort_projects to prevent ImportErrors.
# -------------------------------------------------------------------------
sys.modules["miner_intro"] = MagicMock()
sys.modules["utils"] = MagicMock()

# We also need to mock the decorator inside utils
def mock_measure_time(func):
    return func
sys.modules["utils"].measure_time = mock_measure_time

# Now we can safely import the class
from sort_projects import sort_projects, RateLimitExceededError

# -------------------------------------------------------------------------
# 2. Test Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def mock_apache_data():
    """Sample data resembling apache_projects.json"""
    return {
        "Project A": ["https://github.com/apache/project-a"],
        "Project B": ["https://github.com/apache/project-b", "https://github.com/apache/project-b-experimental"],
        "Project C": ["https://gitbox.apache.org/repos/asf/project-c.git"] # Non-github link
    }

@pytest.fixture
def sorter(tmp_path, mock_apache_data):
    """
    Initialises the sort_projects class with a temporary file path
    so we don't overwrite the real JSON file.
    """
    # Create a temp file
    p = tmp_path / "apache_projects.json"
    p.write_text(json.dumps(mock_apache_data), encoding="utf-8")
    
    # Patch the class attribute path to point to our temp file
    with patch("sort_projects.sort_projects.APACHE_PROJECTS_PATH", p):
        sorter_instance = sort_projects()
        yield sorter_instance

# -------------------------------------------------------------------------
# 3. Unit Tests
# -------------------------------------------------------------------------

def test_init_loads_json_correctly(sorter, mock_apache_data):
    """Test if the JSON data is loaded into the class dictionary on init."""
    assert sorter.apache_projects == mock_apache_data
    assert len(sorter.apache_projects) == 3

def test_get_commit_count_non_github(sorter):
    """Ensure non-GitHub links return 0 immediately."""
    url = "https://gitbox.apache.org/repos/asf/test.git"
    assert sorter.get_commit_count(url) == 0

@patch("requests.Session.get")
def test_get_commit_count_pagination(mock_get, sorter):
    """
    Test logic: If 'Link' header exists, it should parse the 
    'last' page number using regex.
    """
    # Setup mock response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        'Link': '<https://api.github.com/repos/x/y/commits?per_page=1&page=2>; rel="next", <https://api.github.com/repos/x/y/commits?per_page=1&page=50>; rel="last"'
    }
    mock_get.return_value = mock_response

    count = sorter.get_commit_count("https://github.com/apache/test")
    assert count == 50

@patch("requests.Session.get")
def test_get_commit_count_no_pagination(mock_get, sorter):
    """
    Test logic: If no 'Link' header, it should count the length of the JSON list.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {} # No link header
    mock_response.json.return_value = [{"commit": 1}, {"commit": 2}, {"commit": 3}] # 3 items
    mock_get.return_value = mock_response

    count = sorter.get_commit_count("https://github.com/apache/test")
    assert count == 3

@patch("requests.Session.get")
def test_rate_limit_exceeded(mock_get, sorter):
    """Test if RateLimitExceededError is raised correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "API rate limit exceeded"
    mock_response.headers = {'X-RateLimit-Remaining': '0'}
    mock_get.return_value = mock_response

    with pytest.raises(RateLimitExceededError):
        sorter.get_commit_count("https://github.com/apache/test")

def test_analyze_project_logic(sorter):
    """
    Test the worker function _analyze_project.
    We mock get_commit_count so we don't hit the network here.
    """
    project_name = "Test Project"
    links = ["link1", "link2"]
    
    # We patch the method specifically on the instance or class
    with patch.object(sorter, 'get_commit_count', side_effect=[10, 5]):
        result = sorter._analyze_project((project_name, links))
        
        # Unpack result
        p_name, p_links, total, errors = result
        
        assert p_name == "Test Project"
        assert total == 15 # 10 + 5
        assert len(errors) == 0

def test_analyze_project_with_api_error(sorter):
    """Test aggregation when one link fails (returns negative code)."""
    project_name = "Test Project"
    links = ["good_link", "bad_link"]
    
    # First link returns 10, second returns -404 (error)
    with patch.object(sorter, 'get_commit_count', side_effect=[10, -404]):
        result = sorter._analyze_project((project_name, links))
        
        _, _, total, errors = result
        assert total == 10 # Should ignore the error link count
        assert len(errors) == 1
        assert "404" in errors[0]

# -------------------------------------------------------------------------
# 4. Integration Test (Mocking the ThreadPool)
# -------------------------------------------------------------------------

@patch("sort_projects.ThreadPool") 
def test_sort_by_commit_count_integration(mock_pool_cls, sorter):
    """
    Test the full flow:
    1. Mocks ThreadPool to simply return a list of results (bypassing concurrency).
    2. Checks if the file is written with sorted data.
    """
    
    # Mock the pool instance and imap_unordered
    mock_pool = mock_pool_cls.return_value
    
    # We simulate results coming back from the threads
    # Structure: (Name, Links, Count, Errors)
    fake_results = [
        ("Project Low", ["url"], 5, []),
        ("Project High", ["url"], 100, []),
        ("Project Mid", ["url"], 50, [])
    ]
    
    # Make imap_unordered return an iterator of our fake results
    mock_pool.imap_unordered.return_value = iter(fake_results)

    # Run the main sort function
    count = sorter.sort_by_commit_count()

    assert count == 3

    # Now verify the file was written correctly
    # Read the temp file path we set in the fixture
    with open(sorter.APACHE_PROJECTS_PATH, "r") as f:
        data = json.load(f)
    
    # Convert keys to a list to check order
    keys = list(data.keys())
    
    # Should be sorted High -> Mid -> Low
    assert keys == ["Project High", "Project Mid", "Project Low"]

@patch("sort_projects.ThreadPool")
def test_sort_aborts_on_rate_limit(mock_pool_cls, sorter):
    """Test that the file is NOT written if a RateLimitError bubbles up."""
    
    mock_pool = mock_pool_cls.return_value
    
    # Simulate the iterator raising the exception
    mock_pool.imap_unordered.side_effect = RateLimitExceededError("Boom")
    
    # Spy on json.dump to ensure it is NEVER called
    with patch("json.dump") as mock_dump:
        result = sorter.sort_by_commit_count()
        
        assert result == 0
        mock_dump.assert_not_called()