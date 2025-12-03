import datetime
import pytest

from repo_miner import Repo_miner


# ----------------------------------------------------------
# Fake PyDriller-like objects
# ----------------------------------------------------------

class FakeModifiedFile:
    def __init__(self, filename, diff, added=0, removed=0, change_type="MODIFY"):
        self.filename = filename
        self.diff = diff
        self.added_lines = added
        self.deleted_lines = removed

        class CT:
            name = change_type
        self.change_type = CT()


class FakeCommit:
    def __init__(self, hash_, date, modified_files, size):
        self.hash = hash_
        self.committer_date = date
        self.modified_files = modified_files
        self.dmm_unit_size = size


class FakeRepository:
    def __init__(self, url):
        self.url = url
        self._commits = []

    def add_commits(self, commits):
        self._commits.extend(commits)

    def traverse_commits(self):
        for c in self._commits:
            yield c


# ----------------------------------------------------------
# Auto-patch pydriller.Repository
# ----------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_repository(monkeypatch):
    """
    Automatically replace pydriller.Repository with a factory
    that creates and stores FakeRepository instances.
    """
    fake_repos = {}

    def repo_factory(url):
        if url not in fake_repos:
            fake_repos[url] = FakeRepository(url)
        return fake_repos[url]

    monkeypatch.setattr("repo_miner.Repository", repo_factory)
    return fake_repos


# ----------------------------------------------------------
# Tests
# ----------------------------------------------------------

def test_mine_repo_returns_expected_structure(patch_repository):
    miner = Repo_miner()
    repo_url = "https://example.com/repo.git"

    # IMPORTANT: Create the repo by calling the monkeypatched Repository()
    fake_repo = __import__("repo_miner").Repository(repo_url)

    # Fake commits
    c1 = FakeCommit(
        "abc123",
        datetime.datetime(2021, 1, 1, 12, 0),
        [FakeModifiedFile("one.txt", "diff-1")],
        7
    )
    c2 = FakeCommit(
        "def456",
        datetime.datetime(2021, 1, 2, 13, 30),
        [
            FakeModifiedFile("two.py", "diff-2"),
            FakeModifiedFile("three.md", "diff-3")
        ],
        3
    )

    fake_repo.add_commits([c1, c2])

    url, commits = miner.mine_repo(repo_url)

    assert url == repo_url
    assert len(commits) == 2
    assert commits[0]["hash"] == "abc123"
    assert commits[1]["files_changed"]["two.py"] == "diff-2"
    assert commits[1]["size"] == 3


def test_mine_repo_handles_no_modified_files(patch_repository):
    miner = Repo_miner()
    repo_url = "local/path"

    # Create fake repo
    fake_repo = __import__("repo_miner").Repository(repo_url)

    c = FakeCommit(
        "nochange",
        datetime.datetime(2022, 6, 1, 8, 0),
        [],
        0
    )
    fake_repo.add_commits([c])

    url, commits = miner.mine_repo(repo_url)

    assert url == repo_url
    assert len(commits) == 1

    entry = commits[0]
    assert entry["hash"] == "nochange"
    assert entry["files_changed"] == {}
    assert entry["size"] == 0
