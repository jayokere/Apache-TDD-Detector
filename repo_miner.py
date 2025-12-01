from pathlib import Path
import json
import os
from pydriller import Repository
from utils import measure_time
"""
repo_miner.py

Utilities to load local data from ./data and to mine a git repository using PyDriller.
"""

class Repo_miner:
    # Load Apache projects JSON into a module variable
    APACHE_PROJECTS_PATH = Path(__file__).resolve().parent / "data" / "apache_projects.json"
    if APACHE_PROJECTS_PATH.exists():
        with open(APACHE_PROJECTS_PATH, "r", encoding="utf-8") as _f:
            apache_projects = json.load(_f)
    else:
        apache_projects = {}
    @measure_time
    def mine_repo(repo_url):
        """
        Mine a git repository using PyDriller to extract commit data.
        
        Args:
            repo_url (str): The URL of the git repository to mine.
            
        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing commit data.
        """
        commits_data = []
        
        # Use PyDriller to traverse the repository
        for commit in Repository(repo_url).traverse_commits():
            commit_info = {
                'hash': commit.hash,
                'date': commit.committer_date.strftime("%Y-%m-%d %H:%M:%S"),
                'files_changed': {f.filename : f.diff for f in commit.modified_files},
                'size': commit.dmm_unit_size
            }
            commits_data.append(commit_info)
        
        return commits_data


    if __name__ == "__main__":
        for project, links in apache_projects.items():
            print(f"Project: {project}")
            for link in links:
                data = mine_repo(link)
                file_path = f'data/repos/{project}.json'
                file = os.path.dirname(file_path)
                if file:
                    os.makedirs(file, exist_ok=True)
                with open(file_path, 'w') as f:
                    json.dump(data, f, indent=4)

