import pytest, json, os
from unittest.mock import MagicMock, patch, mock_open
from apache_web_miner import Apache_web_miner, fetch_project_data, DATA_FILE

# --- Fixtures ---
@pytest.fixture
def miner():
    return Apache_web_miner("http://fake-url.com", num_threads=1)

# --- Tests for Apache_web_miner Class ---

def test_init(miner):
    assert miner.url == "http://fake-url.com"
    assert miner.data == {}
    assert miner.num_threads == 1

@patch('requests.get')
def test_fetch_data_success(mock_get, miner):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.json.return_value = {"project1": {"name": "Test"}}
    mock_get.return_value = mock_response

    miner.fetch_data()

    assert miner.data == {"project1": {"name": "Test"}}
    mock_get.assert_called_once_with("http://fake-url.com")

@patch('requests.get')
def test_fetch_data_failure(mock_get, miner):
    mock_get.side_effect = Exception("Network Error")
    
    # Should handle exception gracefully (print error) and not crash
    miner.fetch_data()
    assert miner.data == {}

# --- Tests for resolve_redirect ---

@patch('requests.head')
def test_resolve_redirect_success(mock_head, miner):
    # Simulate a link redirecting to GitHub
    mock_response = MagicMock()
    mock_response.url = "https://github.com/apache/test"
    mock_head.return_value = mock_response

    result = miner.resolve_redirect("http://bit.ly/test")
    assert result == "https://github.com/apache/test"

@patch('requests.head')
def test_resolve_redirect_no_github(mock_head, miner):
    # Simulate a link redirecting to something else
    mock_response = MagicMock()
    mock_response.url = "https://google.com"
    mock_head.return_value = mock_response

    result = miner.resolve_redirect("http://bit.ly/test")
    assert result is None

def test_resolve_redirect_invalid_inputs(miner):
    # Test non-string input
    assert miner.resolve_redirect(None) is None
    assert miner.resolve_redirect({"link": "test"}) is None
    
    # Test invalid protocol (e.g., git://)
    assert miner.resolve_redirect("git://github.com/test") is None

# --- Tests for get_github_links (Complex Logic) ---

def test_get_github_links_logic(miner):
    # 1. Setup Mock Data
    miner.data = {
        "proj1": {
            "name": "Project One",
            "repository": [
                "https://github.com/apache/p1",       # Valid direct link
                "http://redirect.me/p1",             # Needs resolving
                {"not": "a string"},                 # Bad data (should skip)
                "https://svn.apache.org/repos/asf"   # Non-GitHub link
            ]
        },
        "proj2": {
            "name": "Project Two",
            # No 'repository' key
        }
    }

    # 2. Mock the resolve_redirect method locally
    # We don't want to use threads or network here, just test the filtering logic
    with patch.object(miner, 'resolve_redirect') as mock_resolve:
        # Define what resolve_redirect returns
        def side_effect(link):
            if link == "http://redirect.me/p1":
                return "https://github.com/apache/p1-resolved"
            return None
        mock_resolve.side_effect = side_effect

        # 3. Run the method
        # Note: We patch ThreadPool to avoid spawning threads in unit tests
        with patch('multiprocessing.pool.ThreadPool') as MockPool:
            pool_instance = MockPool.return_value
            # Mock pool.map to just run the function sequentially for the test
            pool_instance.map.side_effect = lambda func, iterable: [func(i) for i in iterable]
            
            links = miner.get_github_links()

    # 4. Assertions
    expected = {
        "Project One": [
            "https://github.com/apache/p1",
            "https://github.com/apache/p1-resolved"
        ]
    }
    assert links == expected
    # Ensure invalid data (dict) and non-github strings were filtered out
    assert "Project Two" not in links

# --- Tests for fetch_project_data (Integration-like) ---

@patch('os.path.exists')
@patch('builtins.open', new_callable=mock_open, read_data='{"cached": ["data"]}')
def test_fetch_project_data_from_cache(mock_file, mock_exists):
    mock_exists.return_value = True # Simulate file exists
    
    result = fetch_project_data()
    
    assert result == {"cached": ["data"]}
    mock_file.assert_called_with(DATA_FILE, 'r')

@patch('os.path.exists')
@patch('apache_web_miner.Apache_web_miner') # Mock the class itself
@patch('builtins.open', new_callable=mock_open)
@patch('os.makedirs')
def test_fetch_project_data_mining(mock_makedirs, mock_file, MockMiner, mock_exists):
    mock_exists.return_value = False # Simulate file missing
    
    # Setup the mock miner instance
    mock_instance = MockMiner.return_value
    mock_instance.get_github_links.return_value = {"Mined": ["Data"]}
    
    result = fetch_project_data()
    
    # Verify the workflow
    assert result == {"Mined": ["Data"]}
    mock_instance.fetch_data.assert_called_once()
    mock_instance.get_github_links.assert_called_once()
    
    # Verify saving to file
    mock_file.assert_called_with(DATA_FILE, 'w')
    handle = mock_file()
    # Check if json.dump wrote something
    assert handle.write.called