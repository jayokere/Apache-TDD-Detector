import requests
import datetime
import json
import re
import os

from pathlib import Path
from typing import Dict, List

# Internal Modules
import miner_intro
from utils import measure_time

"""
sort_projects.py

Utilities to sort Apache projects based on their GitHub commit activity.
"""

# Check if pyhton-dotenv is available to load environment variables from a .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, we assume the user has set variables in their system environment manually.
    pass

class RateLimitExceededError(Exception):
    """Custom exception raised when GitHub API rate limit is hit."""
    pass

class sort_projects:
    # Load Apache projects JSON into a module variable
    APACHE_PROJECTS_PATH: str = Path(__file__).resolve().parent / "data" / "apache_projects.json"
    API_err: List[str] = []
    is_warning_shown: bool = False
    def __init__(self) -> None:
        if self.APACHE_PROJECTS_PATH.exists():
            with open(self.APACHE_PROJECTS_PATH, "r", encoding="utf-8") as _f:
                self.apache_projects: Dict[str, List[str]] = json.load(_f)
        else:
            self.apache_projects = {}
    
    def get_headers(self) -> Dict[str, str]:
        """
        Returns headers with auth if available, otherwise empty dict.
        """
        token = os.getenv("GITHUB_TOKEN")
        if token:
            # User has setup the token
            return {"Authorization": f"token {token}"}
        else:
            # User has NOT setup the token. 
            # We don't stop them, but they will be limited to 60 requests per hour.
            if  self.is_warning_shown is False:
                self.is_warning_shown = True
                print("💡 You are running in unauthenticated mode (60 reqs/hr).")
                print("   To fix this: Create a GITHUB_TOKEN and export it as an environment variable.")
                print("   This will increase your limit to 5,000 reqs/hr.\n")
            return {}

    def get_commit_count(self, repo_url: str) -> int:
        """
        Get the total number of commits in a git repository.

        Args:
            repo_url (str): The URL of the git repository.
        
        Returns:
            commit_count (int): The total number of commits in the repository.
        """
        # Remove trailing .git and trailing slashes to prevent 404s
        repo_url: str = repo_url.strip().rstrip("/")
        if repo_url.endswith(".git"):
            repo_url: str = repo_url[:-4]

        if "github.com" not in repo_url:
            return 0
        
        api_url: str = repo_url.replace("github.com", "api.github.com/repos") + "/commits?per_page=1"
        headers: Dict[str, str] = self.get_headers()

        try:
            response = requests.get(api_url, headers=headers, timeout=10)
            
            # --- RATE LIMIT CHECK ---
            # We check specific status codes OR the header value
            remaining = response.headers.get('X-RateLimit-Remaining')
            
            is_rate_limited = (
                response.status_code in [403, 429] and "rate limit" in response.text.lower()
            ) or (
                remaining is not None and int(remaining) == 0
            )

            if is_rate_limited:
                reset_val = response.headers.get('X-RateLimit-Reset')
                if reset_val:
                    reset_timestamp = int(reset_val)
                    reset_time = datetime.datetime.fromtimestamp(reset_timestamp, datetime.timezone.utc)
                    msg = f"RATE LIMIT REACHED! Resets at {reset_time}"
                else:
                    msg = "RATE LIMIT REACHED!"
                
                # Raise the custom exception to stop execution
                raise RateLimitExceededError(msg)
            # ------------------------
            
            if response.status_code == 200:
                # Check Link header for pagination
                link_header = response.headers.get('Link')
                if link_header:
                    match = re.search(r'&page=(\d+)>; rel="last"', link_header)
                    if match:
                        return int(match.group(1))
                
                # If no pagination, count the items in the response list
                data = response.json()
                if isinstance(data, list):
                    return len(data)
            else:
                self.API_err.append(f"   ⚠️ API Error {response.status_code} for {repo_url}")
                return 0
            
        except RateLimitExceededError:
            # Re-raise this specific error so the main loop can catch it and stop
            raise
        except Exception as e:
            self.API_err.append(f"⚠️ Error fetching {repo_url}: {e}")
            return 0
    
    @measure_time
    def sort_by_commit_count(self) -> int:
        """
        Sort Apache projects by their commit counts in descending order.

        Returns:
            len(sorted_dict) (int): The number of projects sorted.
        """
        # Temporary list to store (Name, Links, Count)
        scored_projects = []
        total_projects: int = len(self.apache_projects)
        print(f"🚀 Sorting {total_projects} projects by GitHub activity...\n")
        # Flag to track if the process was aborted
        aborted: bool = False 

        # Fetch each project's commit count
        for i, (project, links) in enumerate(self.apache_projects.items()):
            total_commits: int = 0
            for link in links:
                try:
                    total_commits += self.get_commit_count(link)
                except RateLimitExceededError as e:
                    # Catch the stop signal
                    print(f"\n\n🛑 {e}")
                    print("❌ Execution stopped preventing data corruption.")
                    aborted = True
                    break # Break inner loop
                except Exception as e:
                    self.API_err.append(f"⚠️ Error accessing {link}: {e}")
            if aborted:
                break # Break outer loop
            scored_projects.append((project, links, total_commits))
            miner_intro.update_progress(i + 1, total_projects, label="ANALYZING")
        print("\n")

        # If we hit rate limit, we abort without writing the file
        if aborted:
            print("⚠️  Process aborted due to Rate Limit.")
            print("   The 'apache_projects.json' file was NOT updated to preserve integrity.\n")
            return 0

        # Sort by commit count (index 2) in descending order
        scored_projects.sort(key=lambda x: x[2], reverse=True)

        # Rebuild the dictionary in the original format: {Name: [Links]}
        sorted_dict: Dict[str, List[str]] = {item[0]: item[1] for item in scored_projects}
        
        # Print API errors if any
        if self.API_err:
            print("\nAPI Errors encountered during sorting:")
            for err in self.API_err:
                print(err)
        
        # Update the JSON file with the sorted data
        print(f"\nWriting sorted data to {self.APACHE_PROJECTS_PATH}...")
        with open(self.APACHE_PROJECTS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted_dict, f, indent=4)
            
        print("✅ Done! The project list is now sorted by activity.")
        return len(sorted_dict)

if __name__ == "__main__":
    sort_projects().sort_by_commit_count()