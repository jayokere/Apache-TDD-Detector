import pytest
import json
import sys
import os
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
# 1. Mock Internal Modules BEFORE Import
# We must mock 'miner_intro' and 'utils' before importing the target script
# to avoid ImportErrors because those files might not exist in the test env.
# -------------------------------------------------------------------------
sys.modules["miner_intro"] = MagicMock()
sys.modules["utils"] = MagicMock()

# Mock the measure_time decorator to simply return the function
def mock_measure_time(func):
    return func
sys.modules["utils"].measure_time = mock_measure_time

# -------------------------------------------------------------------------
# 2. Import the Main Script
# -------------------------------------------------------------------------
# We import after mocking so the script doesn't crash on 'import miner_intro'
from apache_web_miner import Apache_web_miner, fetch_project_data

# -------------------------------------------------------------------------
# 3. Test Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def mock_apache_json():
    """Sample JSON structure returned by the Apache API."""
    return {
        "project_1": {
            "name": "Apache Foo",
            "repository": [
                "https://github.com/apache/foo",
                "https://gitbox.apache.org/repos/asf/foo.git"
            ]
        },
        "project_2": {
            "name": "Apache Bar",
            "repository": [
                "https://git-wip-us.apache.org/repos/asf/bar.git" # Needs redirect
            ]
        },
        "project_3": {
            "name": "Apache Baz",
            "repository": ["https://svn.apache.org/repos/asf/baz"] # Not a git repo
        }
    }

@pytest.fixture
def miner_instance():
    """Returns an instance of Apache_web_miner with a mocked session."""
    instance = Apache_web_miner("http://fake-url.com", num_threads=1)
    # Mock the session object attached to self to prevent real network calls
    instance.session = MagicMock()
    return instance

# -------------------------------------------------------------------------
# 4. Unit Tests: Apache_web_miner Class
# -------------------------------------------------------------------------

def test_fetch_data_success(miner_instance, mock_apache_json):
    """Test successful data retrieval from the API."""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.json.return_value = mock_apache_json
    miner_instance.session.get.return_value = mock_response

    miner_instance.fetch_data()

    assert miner_instance.data == mock_apache_json
    miner_instance.session.get.assert_called_once_with("http://fake-url.com")

def test_fetch_data_exception(miner_instance, capsys):
    """Test graceful handling of network errors during fetch."""
    miner_instance.session.get.side_effect = Exception("Network Boom")
    
    miner_instance.fetch_data()
    
    # Assert data remains empty
    assert miner_instance.data == {}
    
    # Verify the error was printed (captured by capsys)
    captured = capsys.readouterr()
    assert "An error occurred" in captured.out

def test_resolve_redirect_valid(miner_instance):
    """Test resolving a non-GitHub link that redirects to a GitHub link."""
    # Setup mock HEAD response
    mock_response = MagicMock()
    mock_response.url = "https://github.com/apache/bar"
    miner_instance.session.head.return_value = mock_response

    result = miner_instance.resolve_redirect("http://redirect.me")
    
    assert result == "https://github.com/apache/bar"

def test_resolve_redirect_invalid(miner_instance):
    """Test resolving a link that does NOT redirect to GitHub."""
    mock_response = MagicMock()
    mock_response.url = "https://bitbucket.org/apache/bar" # Not GitHub
    miner_instance.session.head.return_value = mock_response

    result = miner_instance.resolve_redirect("http://redirect.me")
    
    assert result is None

def test_resolve_redirect_bad_input(miner_instance):
    """Test inputs that are not valid strings."""
    assert miner_instance.resolve_redirect(None) is None
    assert miner_instance.resolve_redirect(123) is None

# -------------------------------------------------------------------------
# 5. Integration Logic: get_github_links
# -------------------------------------------------------------------------

@patch("apache_web_miner.ThreadPool")
def test_get_github_links_logic(mock_pool_cls, miner_instance, mock_apache_json):
    """
    Test the extraction and cleaning logic. 
    We mock ThreadPool to bypass actual threads but simulate the 'resolve' results.
    """
    # 1. Load data into the miner
    miner_instance.data = mock_apache_json
    
    # 2. Mock the ThreadPool context manager
    mock_pool = mock_pool_cls.return_value
    mock_pool.__enter__.return_value = mock_pool
    mock_pool.__exit__.return_value = None

    # 3. Simulate results from the worker threads
    # The code expects: (original_link, resolved_link)
    fake_thread_results = [
        ("https://gitbox.apache.org/repos/asf/foo.git", None),
        ("https://git-wip-us.apache.org/repos/asf/bar.git", "https://github.com/apache/bar"),
        ("https://svn.apache.org/repos/asf/baz", None)
    ]
    
    # We just return an iterator of the results.
    mock_pool.imap_unordered.return_value = iter(fake_thread_results)

    # 4. Run the method
    result_dict = miner_instance.get_github_links()

    # 5. Assertions
    # Project 1: Had one direct GitHub link.
    assert "https://github.com/apache/foo" in result_dict["Apache Foo"]
    
    # Project 2: Had no direct links, but one resolved to GitHub.
    assert "https://github.com/apache/bar" in result_dict["Apache Bar"]
    
    # Project 3: No direct links, no resolved links. Should not be in dict.
    assert "Apache Baz" not in result_dict

# -------------------------------------------------------------------------
# 6. Tests for fetch_project_data (File I/O)
# -------------------------------------------------------------------------

def test_fetch_project_data_local_file_exists(tmp_path):
    """
    If the file exists locally, it should simply load it 
    and NOT trigger the miner.
    """
    # Create dummy data
    fake_data = {"Project X": ["http://github.com/x"]}
    p = tmp_path / "apache_projects.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fake_data), encoding="utf-8")

    # Patch the DATA_FILE constant in the apache_web_miner module
    with patch("apache_web_miner.DATA_FILE", str(p)):
        # Patch Apache_web_miner class so we can verify it was NOT initialized
        with patch("apache_web_miner.Apache_web_miner") as MockMiner:
            
            result = fetch_project_data()
            
            assert result == fake_data
            MockMiner.assert_not_called()

def test_fetch_project_data_no_local_file(tmp_path):
    """
    If local file is missing, it should:
    1. Initialize Miner
    2. Fetch Data
    3. Get Links
    4. Write result to file
    """
    target_file = tmp_path / "new_data.json"
    
    # Mock return data from miner
    fake_mined_data = {"Mined Project": ["https://github.com/mined"]}

    with patch("apache_web_miner.DATA_FILE", str(target_file)):
        with patch("apache_web_miner.Apache_web_miner") as MockMinerCls:
            # Configure the mock instance
            mock_instance = MockMinerCls.return_value
            mock_instance.get_github_links.return_value = fake_mined_data
            
            result = fetch_project_data()

            # Assertions
            assert result == fake_mined_data
            mock_instance.fetch_data.assert_called_once()
            mock_instance.get_github_links.assert_called_once()
            
            # Verify file was written
            assert target_file.exists()
            with open(target_file, 'r') as f:
                saved_content = json.load(f)
            assert saved_content == fake_mined_data