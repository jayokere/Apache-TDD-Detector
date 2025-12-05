import pytest
import sys
import os
from unittest.mock import MagicMock, patch, call

# -------------------------------------------------------------------------
# 1. Mock External Dependencies BEFORE Importing the Unit Under Test
# -------------------------------------------------------------------------
# We mock 'db' and 'utils' so we don't need real database connections
# or the actual utils module present.
sys.modules["db"] = MagicMock()
sys.modules["utils"] = MagicMock()

# Mock the measure_time decorator to just run the function
sys.modules["utils"].measure_time = lambda func: func

# Now safely import the class
from repo_miner import Repo_miner

# -------------------------------------------------------------------------
# 2. Test Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def miner():
    """Creates a Repo_miner instance with mocked DB calls."""
    # Mock the project fetch inside __init__
    with patch("repo_miner.get_projects_to_mine") as mock_get_projects:
        mock_get_projects.return_value = [
            {"name": "Project A", "urls": ["http://github.com/a"]},
            {"name": "Project B", "urls": ["http://github.com/b"]}
        ]
        miner_instance = Repo_miner()
        return miner_instance

@pytest.fixture
def mock_commit():
    """Creates a dummy PyDriller commit object."""
    commit = MagicMock()
    commit.hash = "abc123456789"
    commit.msg = "Test commit message"
    commit.committer_date = "2024-01-01"
    
    # Create mock ModifiedFile objects
    file1 = MagicMock()
    file1.filename = "TestClass.java"
    
    file2 = MagicMock()
    file2.filename = "ProductionCode.py"
    
    file3 = MagicMock()
    file3.filename = "README.md" # Should be filtered out
    
    commit.modified_files = [file1, file2, file3]
    return commit

# -------------------------------------------------------------------------
# 3. Unit Tests: Static Helper Methods
# -------------------------------------------------------------------------

def test_clean_url():
    """Test URL sanitization logic."""
    # Valid HTTPS
    assert Repo_miner.clean_url("https://github.com/apache/spark") == "https://github.com/apache/spark"
    # Trailing slashes
    assert Repo_miner.clean_url("https://github.com/apache/spark/  ") == "https://github.com/apache/spark"
    # SCP-like syntax (the specific bug fix)
    assert Repo_miner.clean_url("https://user:pass@github.com:apache/spark.git") == "https://user:pass@github.com/apache/spark.git"
    # None handling
    assert Repo_miner.clean_url(None) is None

def test_identify_files_logic():
    """Test the file filtering logic (Tests + Source Code)."""
    
    # Mix of files
    files = [
        MagicMock(filename="Main.java"),       # Source (Keep)
        MagicMock(filename="test_utils.py"),   # Test (Keep)
        MagicMock(filename="image.png"),       # Asset (Drop)
        MagicMock(filename="config.xml"),      # Config (Drop)
        MagicMock(filename="script.sh"),       # Unknown ext (Drop)
        MagicMock(filename=None)               # Invalid (Drop)
    ]
    
    kept = Repo_miner.identify_files(files)
    
    assert "Main.java" in kept
    assert "test_utils.py" in kept
    assert "image.png" not in kept
    assert "config.xml" not in kept
    assert len(kept) == 2

# -------------------------------------------------------------------------
# 4. Unit Tests: Worker Logic (mine_repo)
# -------------------------------------------------------------------------

@patch("repo_miner.Repository")
@patch("repo_miner.get_existing_commit_hashes")
@patch("repo_miner.save_commit_batch")
def test_mine_repo_normal_flow(mock_save, mock_get_hashes, mock_repo_cls):
    """
    Test a successful mining run where:
    1. One commit is already in DB (skipped).
    2. One commit is new and relevant (saved).
    3. One commit is new but irrelevant/docs (skipped).
    """
    # Setup args
    project_name = "TestProject"
    url = "http://github.com/test"
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    # 1. Mock DB Hashes (Commit A is already known)
    mock_get_hashes.return_value = {"hash_A"}
    
    # 2. Mock PyDriller Repository Commits
    commit_A = MagicMock(hash="hash_A") # Existing
    
    commit_B = MagicMock(hash="hash_B", msg="New Code", committer_date="2024") # Relevant
    commit_B.modified_files = [MagicMock(filename="App.java")]
    
    commit_C = MagicMock(hash="hash_C", msg="Docs", committer_date="2024") # Irrelevant
    commit_C.modified_files = [MagicMock(filename="README.md")]
    
    mock_repo_instance = mock_repo_cls.return_value
    mock_repo_instance.traverse_commits.return_value = [commit_A, commit_B, commit_C]
    
    # Run
    result = Repo_miner.mine_repo((project_name, url, stop_event))
    
    # Assertions
    # Return format: (project, added_count, existing_count, error)
    assert result == (project_name, 1, 1, None)
    
    # Verify save was called exactly once for commit_B
    mock_save.assert_called_once()
    saved_batch = mock_save.call_args[0][0]
    assert len(saved_batch) == 1
    assert saved_batch[0]['hash'] == "hash_B"
    assert saved_batch[0]['files'] == ["App.java"]

def test_mine_repo_stop_event():
    """Test immediate exit if stop_event is set."""
    stop_event = MagicMock()
    stop_event.is_set.return_value = True
    
    result = Repo_miner.mine_repo(("Proj", "url", stop_event))
    assert result is None

def test_mine_repo_bad_url():
    """Test the guard clause for invalid URLs."""
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    result = Repo_miner.mine_repo(("Proj", None, stop_event))
    
    # ADD THIS LINE: Assert result is not None to satisfy Pylance
    assert result is not None 
    
    # Should return an error tuple indicating skip
    assert result[3] == "Skipped: Invalid or missing URL"

@patch("repo_miner.Repository")
def test_mine_repo_exception_handling(mock_repo_cls):
    """Test that worker catches exceptions and returns them safely."""
    stop_event = MagicMock()
    stop_event.is_set.return_value = False
    
    # Make PyDriller crash
    mock_repo_cls.side_effect = Exception("Git Error")
    
    result = Repo_miner.mine_repo(("Proj", "http://bad.url", stop_event))
    
    # ADD THIS LINE: Assert result is not None
    assert result is not None
    
    assert result[0] == "Proj"
    assert result[3] == "Git Error"

# -------------------------------------------------------------------------
# 5. Integration Test: The Run Loop
# -------------------------------------------------------------------------

@patch("repo_miner.ProcessPoolExecutor")
@patch("repo_miner.as_completed")
@patch("repo_miner.ensure_indexes")
@patch("repo_miner.tqdm")
def test_run_orchestration(mock_tqdm, mock_ensure_idx, mock_as_completed, mock_executor, miner):
    """
    Test that the main loop submits jobs and processes results.
    """
    # Setup mocks
    mock_manager = MagicMock()
    mock_executor_instance = mock_executor.return_value
    mock_executor_instance.__enter__.return_value = mock_executor_instance
    
    # Create fake Futures
    future_success = MagicMock()
    future_success.result.return_value = ("Project A", 10, 5, None)
    
    future_fail = MagicMock()
    future_fail.result.return_value = ("Project B", 0, 0, "Network Error")
    
    mock_as_completed.return_value = [future_success, future_fail]
    
    # Run
    # We patch Manager context manager to avoid multiprocessing overhead
    with patch("repo_miner.Manager", return_value=mock_manager):
        miner.run()
    
    # Verify jobs submitted
    # We have 2 projects in the fixture, so 2 submits expected
    assert mock_executor_instance.submit.call_count == 2
    
    # Verify results logging
    # 'tqdm.write' should be called for success and failure messages
    assert mock_tqdm.write.call_count >= 2
    
    # Verify indexes created at end
    mock_ensure_idx.assert_called_once()