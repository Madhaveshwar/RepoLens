import re
from github import Github
from backend.app.utils.logger import get_logger

logger = get_logger("github_service")

def parse_repo_url(url: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    match = re.search(r'(?:github\.com[:/]|git@github\.com:)([^/]+)/([^/.]+)(?:\.git)?', url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    parts = [p for p in url.split("/") if p]
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    elif len(parts) > 2:
        if "github.com" in parts:
            idx = parts.index("github.com")
            if idx + 2 < len(parts):
                return f"{parts[idx+1]}/{parts[idx+2]}"
        return f"{parts[-2]}/{parts[-1]}"
    return None

class GitHubService:
    def __init__(self, token: str | None = None):
        import os
        from github import GithubIntegration
        from backend.app.config import settings
        
        self.token = token.strip() if token else None
        self.integration = None
        
        app_id = settings.GITHUB_APP_ID
        private_key = settings.GITHUB_APP_PRIVATE_KEY
        
        if app_id and private_key:
            if "-----BEGIN" not in private_key and os.path.exists(private_key):
                try:
                    with open(private_key, "r") as f:
                        private_key_content = f.read()
                except Exception as fe:
                    logger.error(f"Failed to read GitHub App private key file: {fe}")
                    private_key_content = private_key
            else:
                private_key_content = private_key.replace("\\n", "\n")
                
            try:
                self.integration = GithubIntegration(int(app_id), private_key_content)
                logger.info(f"GitHub App Integration initialized successfully (App ID: {app_id})")
            except Exception as e:
                logger.error(f"Failed to initialize GitHub App Integration: {e}", exc_info=True)
                
        logger.info(f"Initializing GitHubService (has_token: {bool(self.token)}, has_app_integration: {bool(self.integration)})")
        if self.token:
            self.client = Github(self.token)
        else:
            self.client = Github()

    def get_client_for_repo(self, repo_name: str) -> Github:
        """Get an authenticated Github client for a specific repository."""
        if self.token:
            return Github(self.token)
        if self.integration:
            try:
                parts = repo_name.split("/")
                if len(parts) >= 2:
                    owner = parts[-2]
                    repo = parts[-1]
                    installation = self.integration.get_repo_installation(owner, repo)
                    token = self.integration.get_access_token(installation.id).token
                    return Github(token)
            except Exception as e:
                logger.warning(f"Failed to fetch installation client for {repo_name} from GitHub App, falling back: {e}")
        return self.client

    def get_repo_details(self, repo_name: str) -> dict[str, object]:
        from github import GithubException
        logger.info(f"Fetching repository details for: {repo_name}")
        try:
            client = self.get_client_for_repo(repo_name)
            repo = client.get_repo(repo_name)
            is_archived = getattr(repo, "archived", False)
            is_empty = False
            default_branch = repo.default_branch
            if not default_branch:
                is_empty = True
            
            if not is_empty:
                try:
                    repo.get_branch(default_branch)
                except GithubException as ge:
                    if ge.status == 404:
                        is_empty = True
                    else:
                        raise ge
            
            open_pulls = repo.get_pulls(state="open")
            open_prs_count = open_pulls.totalCount
            total_issues_and_prs = repo.open_issues_count
            open_issues_count = max(0, total_issues_and_prs - open_prs_count)
 
            logger.info(f"Successfully retrieved repository details for {repo_name}. Open PRs: {open_prs_count}, Issues: {open_issues_count}")
            return {
                "name": repo.full_name,
                "description": repo.description or "No description provided.",
                "stars": repo.stargazers_count,
                "forks": repo.forks_count,
                "open_prs_count": open_prs_count,
                "open_issues_count": open_issues_count,
                "default_branch": default_branch,
                "languages": repo.get_languages(),
                "archived": is_archived,
                "is_empty": is_empty,
            }
        except GithubException as ge:
            logger.error(f"GitHubException fetching repo {repo_name}: {ge.status} - {ge.data}", exc_info=True)
            if ge.status == 404:
                raise ValueError("Repository not found. Double check the owner/repo name, or check your GITHUB_TOKEN permissions.")
            elif ge.status == 403:
                raise ValueError("GitHub API rate limit exceeded. Please configure a valid GITHUB_TOKEN.")
            else:
                raise ValueError(f"GitHub API Error ({ge.status}): {ge.data.get('message', str(ge))}")
 
    def get_open_pull_requests(self, repo_name: str) -> list[dict[str, object]]:
        logger.info(f"Fetching open pull requests for repo: {repo_name}")
        try:
            client = self.get_client_for_repo(repo_name)
            repo = client.get_repo(repo_name)
            pulls = repo.get_pulls(state="open", sort="created", direction="desc")
            pr_list = []
            for pr in pulls:
                try:
                    additions = pr.additions
                    deletions = pr.deletions
                except Exception as lazy_err:
                    logger.warning(f"Failed to lazy load additions/deletions for PR #{pr.number}: {lazy_err}")
                    additions = 0
                    deletions = 0
                
                try:
                    head_sha = pr.head.sha
                    base_sha = pr.base.sha
                except Exception as lazy_err:
                    logger.warning(f"Failed to lazy load head/base SHA for PR #{pr.number}: {lazy_err}")
                    head_sha = ""
                    base_sha = ""

                pr_list.append({
                    "number": pr.number,
                    "title": pr.title,
                    "author": pr.user.login if pr.user else "unknown",
                    "state": pr.state or "open",
                    "additions": additions,
                    "deletions": deletions,
                    "head_sha": head_sha,
                    "base_sha": base_sha,
                    "created_at": pr.created_at.strftime("%Y-%m-%d") if pr.created_at else "",
                })
            logger.info(f"Retrieved {len(pr_list)} open PRs for repo {repo_name}")
            return pr_list
        except Exception as e:
            logger.error(f"Failed to fetch open PRs for repo {repo_name}: {e}", exc_info=True)
            raise
 
    def get_pr_details(self, repo_name: str, pr_number: int) -> dict[str, object]:
        logger.info(f"Fetching details for PR #{pr_number} on repo: {repo_name}")
        try:
            client = self.get_client_for_repo(repo_name)
            repo = client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            logger.info(f"Retrieved details for PR #{pr_number}: title='{pr.title}', status={pr.state}")
            return {
                "number": pr.number,
                "title": pr.title,
                "author": pr.user.login,
                "files_changed_count": pr.changed_files,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "state": pr.state,
                "head_sha": pr.head.sha,
                "base_sha": pr.base.sha,
                "created_at": pr.created_at.strftime("%Y-%m-%d"),
            }
        except Exception as e:
            logger.error(f"Failed to fetch PR details for #{pr_number} on {repo_name}: {e}", exc_info=True)
            raise
 
    def get_pr_files(self, repo_name: str, pr_number: int) -> list[dict[str, object]]:
        logger.info(f"Fetching changed files list for PR #{pr_number} on repo: {repo_name}")
        try:
            client = self.get_client_for_repo(repo_name)
            repo = client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            files = []
            for f in pr.get_files():
                files.append({
                    "filename": f.filename,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "changes": f.changes,
                    "status": f.status,
                    "patch": f.patch or "",
                    "raw_url": f.raw_url,
                })
            logger.info(f"Retrieved {len(files)} changed files for PR #{pr_number} on {repo_name}")
            return files
        except Exception as e:
            logger.error(f"Failed to fetch files for PR #{pr_number} on {repo_name}: {e}", exc_info=True)
            raise
 
    def get_file_content(self, repo_name: str, path: str, ref: str) -> str:
        logger.info(f"Fetching file content for {path} (ref: {ref}) in repo: {repo_name}")
        try:
            client = self.get_client_for_repo(repo_name)
            repo = client.get_repo(repo_name)
            content_file = repo.get_contents(path, ref=ref)
            if isinstance(content_file, list):
                logger.warning(f"Path {path} returned a directory listing, not a file.")
                return ""
            content = content_file.decoded_content.decode("utf-8", errors="replace")
            logger.info(f"Successfully fetched {len(content)} characters of content for file {path}")
            return content
        except Exception as e:
            logger.error(f"Failed to fetch file content for {path} (ref: {ref}) in {repo_name}: {e}", exc_info=True)
            return ""
 
    def get_modified_lines(self, patch: str) -> set[int]:
        if not patch:
            return set()
        modified_lines = set()
        current_line = 0
        hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
 
        for line in patch.splitlines():
            match = hunk_header_re.match(line)
            if match:
                current_line = int(match.group(1))
            elif line.startswith("+"):
                modified_lines.add(current_line)
                current_line += 1
            elif line.startswith("-"):
                pass
            else:
                current_line += 1
        return modified_lines
 
    def find_diff_position(self, patch: str, target_line: int) -> int | None:
        if not patch:
            return None
        lines = patch.splitlines()
        diff_line_count = 0
        current_new_line = 0
        first_hunk_found = False
 
        for line in lines:
            if line.startswith("@@"):
                first_hunk_found = True
                match = re.search(r"\+(\d+)(?:,\d+)?", line)
                if match:
                    current_new_line = int(match.group(1))
                else:
                    current_new_line = 1
 
            if first_hunk_found:
                diff_line_count += 1
                if not line.startswith("@@"):
                    if not line.startswith("-"):
                        if current_new_line == target_line:
                            return diff_line_count
                        current_new_line += 1
        return None
 
    def post_comment(self, repo_name: str, pr_number: int, body: str) -> bool:
        logger.info(f"Posting PR review main comment to PR #{pr_number} on {repo_name}")
        try:
            client = self.get_client_for_repo(repo_name)
            repo = client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            pr.create_issue_comment(body)
            logger.info("PR comment posted successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to post PR main comment: {e}", exc_info=True)
            return False
 
    def post_inline_comments(
        self, repo_name: str, pr_number: int, inline_comments: list[dict[str, object]]
    ) -> tuple[int, int]:
        logger.info(f"Posting {len(inline_comments)} inline comments to PR #{pr_number} on {repo_name}")
        # Resolve client to verify auth credentials
        client = self.get_client_for_repo(repo_name)
        try:
            repo = client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            commits = list(pr.get_commits())
            if not commits:
                logger.error("No commits found in PR. Cannot post review comments.")
                return 0, len(inline_comments)
            latest_commit = commits[-1]
 
            posted = 0
            failed = 0
            for comment in inline_comments:
                filename = comment.get("file")
                line = comment.get("line")
                body = comment.get("body")
                if not filename or not line or not body:
                    logger.warning(f"Incomplete comment object skipped: {comment}")
                    failed += 1
                    continue
                try:
                    pr.create_review_comment(
                        body=body,
                        commit=latest_commit,
                        path=filename,
                        line=int(line),
                        side="RIGHT"
                    )
                    posted += 1
                except Exception as e:
                    logger.error(f"Failed to post inline comment for {filename}:{line}: {e}", exc_info=True)
                    failed += 1
            logger.info(f"Inline comments posting finished: {posted} posted, {failed} failed.")
            return posted, failed
        except Exception as exc:
            logger.error(f"Error posting inline comments: {exc}", exc_info=True)
            return 0, len(inline_comments)
