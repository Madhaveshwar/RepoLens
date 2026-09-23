import json
import csv
import io
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import datetime

def clean_pdf_text(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u2013": "-", "\u2014": "-",
        "\u2022": "*", "\u2192": "->", "\u2714": "[Yes]", "\u2716": "[No]", "🐍": "Python",
        "🟨": "JS", "🔷": "TS", "☕": "Java", "⚙️": "C/C++", "🦀": "Rust", "🐘": "PHP",
        "🐹": "Go", "🍎": "Swift", "🌐": "HTML/CSS", "🚀": "Launch", "⚠️": "Warning",
        "🛑": "Error", "✅": "OK", "❌": "Fail", "📁": "Folder", "📄": "File", "💡": "Tip",
        "🔍": "Scan", "📊": "Chart", "🛡️": "Security", "💯": "100", "⭐": "Star", "🍴": "Fork",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", errors="replace").decode("latin-1")

class PDFReport(FPDF):
    def __init__(self, repo_name: str, pr_number: int | None = None):
        super().__init__()
        self.repo_name = repo_name
        self.pr_number = pr_number

    def header(self):
        self.set_fill_color(15, 23, 42)
        self.rect(0, 0, 210, 25, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 12)
        self.set_y(8)
        self.cell(0, 10, clean_pdf_text(f"RepoLens AI - {self.repo_name}"), border=0, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
        if self.pr_number:
            self.cell(0, 10, clean_pdf_text(f"PR #{self.pr_number}"), border=0, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.ln(20)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(148, 163, 184)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", border=0, align="C", new_x=XPos.RIGHT, new_y=YPos.TOP)

def generate_markdown_report(data: dict[str, object]) -> str:
    repo_name = data.get("repo_name", "Local Scan")
    pr_number = data.get("pr_number")
    risk_score = data.get("risk_score", 0)
    findings = data.get("findings", [])
    test_suggestions = data.get("test_suggestions", "")
    repo_analysis = data.get("repo_analysis", {})
    files_log = data.get("files_analyzed_log", [])
    scores = data.get("scores", {})

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = f.get("severity", "Info")
        if sev in severity_counts:
            severity_counts[sev] += 1

    md = []
    md.append(f"# RepoLens AI Report - {repo_name}")
    if pr_number:
        md.append(f"**Pull Request:** #{pr_number}")
    md.append(f"**Generated at:** {data.get('timestamp', 'N/A')}\n")

    md.append("## Executive Summary")
    md.append(f"- **Overall Risk Score:** {risk_score}/100")
    md.append("- **Findings Breakdown:**")
    for sev, count in severity_counts.items():
        md.append(f"  - {sev}: {count}")
    md.append(f"  - **Total Issues:** {len(findings)}\n")

    if scores:
        md.append("- **Platform Quality Scores:**")
        md.append(f"  - Code Quality: {scores.get('code_quality', 0)}/100")
        md.append(f"  - Security Score: {scores.get('security', 0)}/100")
        md.append(f"  - Maintainability Score: {scores.get('maintainability', 0)}/100")
        md.append(f"  - Performance Score: {scores.get('performance', 0)}/100")
        md.append(f"  - Technical Debt Score: {scores.get('technical_debt', 0)}/100\n")

    if files_log:
        md.append("## Files Analyzed")
        md.append("| File | Type | Status | Findings |")
        md.append("| --- | --- | --- | --- |")
        for item in files_log:
            md.append(f"| `{item.get('file')}` | {item.get('type')} | {item.get('status')} | {item.get('findings')} |")
        md.append("\n")

    if findings:
        md.append("## Findings Grouped By File")
        by_file = {}
        for f in findings:
            by_file.setdefault(f.get("file"), []).append(f)
        for fname, file_findings in by_file.items():
            md.append(f"### `{fname}`\n")
            sec_finds = [f for f in file_findings if f.get("category") == "Security"]
            smells = [f for f in file_findings if f.get("category") == "Code Smell"]
            other_finds = [f for f in file_findings if f.get("category") not in ["Security", "Code Smell"]]
            
            if sec_finds:
                md.append("#### Security Findings")
                for sf in sec_finds:
                    md.append(f"- **Line {sf.get('line')}** [{sf.get('severity')}]: {sf.get('issue')}")
                    md.append(f"  *Risk Level:* {sf.get('risk_level', sf.get('severity'))}")
                    md.append(f"  *Why it matters:* {sf.get('why_it_matters', 'See suggestion details.')}")
                    md.append(f"  *Recommendation:* {sf.get('suggestion')}")
                    before_code = sf.get("before_code")
                    after_code = sf.get("after_code")
                    if before_code or after_code:
                        md.append("  *Refactoring Comparison:*")
                        if before_code:
                            md.append(f"  ```\n  // BEFORE (Insecure):\n{before_code}\n  ```")
                        if after_code:
                            md.append(f"  ```\n  // AFTER (Remediated):\n{after_code}\n  ```")
                md.append("")
                
            if smells:
                md.append("#### Code Smells")
                for s in smells:
                    md.append(f"- **Line {s.get('line')}** [{s.get('severity')}]: {s.get('issue')}")
                    md.append(f"  *Risk Level:* {s.get('risk_level', s.get('severity'))}")
                    md.append(f"  *Why it matters:* {s.get('why_it_matters', 'See suggestion details.')}")
                    md.append(f"  *Recommendation:* {s.get('suggestion')}")
                    before_code = s.get("before_code")
                    after_code = s.get("after_code")
                    if before_code or after_code:
                        md.append("  *Refactoring Comparison:*")
                        if before_code:
                            md.append(f"  ```\n  // BEFORE (Smell):\n{before_code}\n  ```")
                        if after_code:
                            md.append(f"  ```\n  // AFTER (Clean):\n{after_code}\n  ```")
                md.append("")
                
            if other_finds:
                md.append("#### General Findings")
                for of in other_finds:
                    md.append(f"- **Line {of.get('line')}** [{of.get('severity')}]: {of.get('issue')}")
                    md.append(f"  *Risk Level:* {of.get('risk_level', of.get('severity'))}")
                    md.append(f"  *Why it matters:* {of.get('why_it_matters', 'See suggestion details.')}")
                    md.append(f"  *Recommendation:* {of.get('suggestion')}")
                    before_code = of.get("before_code")
                    after_code = of.get("after_code")
                    if before_code or after_code:
                        md.append("  *Refactoring Comparison:*")
                        if before_code:
                            md.append(f"  ```\n  // BEFORE:\n{before_code}\n  ```")
                        if after_code:
                            md.append(f"  ```\n  // AFTER (Remediated/Optimized):\n{after_code}\n  ```")
                md.append("")

    md.append("## Executive Issues List")
    if not findings:
        md.append("No issues found! Code quality is clean.")
    else:
        md.append("| File | Line | Severity | Category | Issue | Suggestion |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        for f in findings:
            md.append(f"| `{f.get('file')}` | {f.get('line')} | **{f.get('severity')}** | {f.get('category')} | {f.get('issue')} | {f.get('suggestion')} |")
        md.append("\n")

    if test_suggestions:
        md.append("## Test Case Suggestions")
        md.append(test_suggestions)
        md.append("\n")

    if repo_analysis and isinstance(repo_analysis, dict):
        md.append("## Repository Health Analysis")
        md.append(f"- **Repository Health Score:** {repo_analysis.get('health_score', 0)}/100")
        md.append("- **Repository Summary:**")
        analysis_report = repo_analysis.get("analysis_report")
        if analysis_report:
            md.append(str(analysis_report))
        else:
            md.append("No qualitative analysis available.")

    return "\n".join(md)

def generate_json_report(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2)

def generate_csv_report(data: dict[str, object]) -> str:
    findings = data.get("findings", [])
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(["File", "Line", "Severity", "Category", "Issue", "Suggestion", "Why It Matters", "Before Code", "After Code"])
    
    # Rows
    for f in findings:
        writer.writerow([
            f.get("file", ""),
            f.get("line", ""),
            f.get("severity", ""),
            f.get("category", ""),
            f.get("issue", ""),
            f.get("suggestion", ""),
            f.get("why_it_matters", ""),
            f.get("before_code", ""),
            f.get("after_code", "")
        ])
    return output.getvalue()

def generate_pdf_report(data: dict[str, object], output_filepath: str) -> None:
    repo_name = data.get("repo_name", "Local Scan")
    pr_number = data.get("pr_number")
    risk_score = data.get("risk_score", 0)
    findings = data.get("findings", [])
    test_suggestions = data.get("test_suggestions", "")
    repo_analysis = data.get("repo_analysis", {})

    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0, "Info": 0}
    for f in findings:
        sev = f.get("severity", "Info")
        if sev in severity_counts:
            severity_counts[sev] += 1

    pdf = PDFReport(repo_name, pr_number)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Title
    pdf.set_text_color(15, 23, 42)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, clean_pdf_text("Pull Request Code Review Report"), border=0, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, clean_pdf_text(f"Generated on: {data.get('timestamp', 'N/A')}"), border=0, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # Executive Summary Box
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(10, 42, 190, 45, "DF")

    pdf.set_xy(15, 45)
    pdf.set_text_color(15, 23, 42)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, clean_pdf_text("Executive Summary"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, clean_pdf_text(f"Overall PR Risk Score: {risk_score}/100"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    breakdown_parts = [f"{k}: {v}" for k, v in severity_counts.items()]
    pdf.cell(0, 6, clean_pdf_text(f"Issues Breakdown: {', '.join(breakdown_parts)}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, clean_pdf_text(f"Total Findings: {len(findings)} files scanned."), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(18)

    # Key Findings Table
    pdf.set_text_color(15, 23, 42)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, clean_pdf_text("Key Findings"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if not findings:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 10, clean_pdf_text("No major issues found. The code changes follow good practices."), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        # Table headers
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(241, 245, 249)
        pdf.cell(40, 7, clean_pdf_text("File"), border=1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(12, 7, clean_pdf_text("Line"), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(18, 7, clean_pdf_text("Severity"), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(25, 7, clean_pdf_text("Category"), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(95, 7, clean_pdf_text("Issue / Suggestion"), border=1, align="L", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 8.5)
        for i, f in enumerate(findings):
            fill = (i % 2 == 1)
            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)

            file_name = f.get("file", "")
            if len(file_name) > 22:
                file_name = "..." + file_name[-19:]

            severity = f.get("severity", "")
            category = f.get("category", "")
            issue = f.get("issue", "")
            suggestion = f.get("suggestion", "")
            issue_text = f"{issue}: {suggestion}"

            if len(issue_text) > 65:
                issue_text = issue_text[:62] + "..."

            pdf.cell(40, 7, clean_pdf_text(file_name), border=1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(12, 7, str(f.get("line", "")), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            
            if severity in ["Critical", "High"]:
                pdf.set_text_color(185, 28, 28)
            elif severity == "Medium":
                pdf.set_text_color(194, 65, 12)
            else:
                pdf.set_text_color(15, 23, 42)
            pdf.cell(18, 7, clean_pdf_text(severity), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_text_color(15, 23, 42)

            pdf.cell(25, 7, clean_pdf_text(category), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(95, 7, clean_pdf_text(issue_text), border=1, align="L", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # Files Analyzed
    files_log = data.get("files_analyzed_log", [])
    if files_log:
        pdf.add_page()
        pdf.set_text_color(15, 23, 42)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, clean_pdf_text("Files Analyzed"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(241, 245, 249)
        pdf.cell(100, 7, clean_pdf_text("File"), border=1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 7, clean_pdf_text("Type"), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 7, clean_pdf_text("Status"), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 7, clean_pdf_text("Findings"), border=1, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 8.5)
        for i, item in enumerate(files_log):
            fill = (i % 2 == 1)
            pdf.set_fill_color(248, 250, 252) if fill else pdf.set_fill_color(255, 255, 255)

            fname = item.get("file", "")
            if len(fname) > 55:
                fname = "..." + fname[-52:]

            pdf.cell(100, 7, clean_pdf_text(fname), border=1, align="L", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(30, 7, clean_pdf_text(str(item.get("type", ""))), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(30, 7, clean_pdf_text(str(item.get("status", ""))), border=1, align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(30, 7, str(item.get("findings", 0)), border=1, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(5)

    # Detailed Grouped findings
    if findings:
        pdf.add_page()
        pdf.set_text_color(15, 23, 42)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, clean_pdf_text("Findings Grouped By File"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

        by_file = {}
        for f in findings:
            by_file.setdefault(f.get("file"), []).append(f)

        for fname, file_findings in by_file.items():
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(31, 111, 235)
            pdf.cell(0, 8, clean_pdf_text(f"File: {fname}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(15, 23, 42)

            sec_finds = [f for f in file_findings if f.get("category") == "Security"]
            smells = [f for f in file_findings if f.get("category") == "Code Smell"]
            other_finds = [f for f in file_findings if f.get("category") not in ["Security", "Code Smell"]]

            if sec_finds:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(10, 5, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(0, 5, clean_pdf_text("Security Findings:"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                for sf in sec_finds:
                    pdf.set_font("Helvetica", "I", 8.5)
                    pdf.cell(15, 5, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 5, clean_pdf_text(f"- Line {sf.get('line')} [{sf.get('severity')}]: {sf.get('issue')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("Helvetica", "", 8)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Risk Level: {sf.get('risk_level', sf.get('severity'))}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Why it matters: {sf.get('why_it_matters', 'N/A')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Recommendation: {sf.get('suggestion')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            if smells:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(10, 5, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(0, 5, clean_pdf_text("Code Smells:"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                for s in smells:
                    pdf.set_font("Helvetica", "I", 8.5)
                    pdf.cell(15, 5, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 5, clean_pdf_text(f"- Line {s.get('line')} [{s.get('severity')}]: {s.get('issue')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("Helvetica", "", 8)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Risk Level: {s.get('risk_level', s.get('severity'))}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Why it matters: {s.get('why_it_matters', 'N/A')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Recommendation: {s.get('suggestion')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            if other_finds:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(10, 5, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(0, 5, clean_pdf_text("General Findings:"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                for of in other_finds:
                    pdf.set_font("Helvetica", "I", 8.5)
                    pdf.cell(15, 5, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 5, clean_pdf_text(f"- Line {of.get('line')} [{of.get('severity')}]: {of.get('issue')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.set_font("Helvetica", "", 8)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Risk Level: {of.get('risk_level', of.get('severity'))}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Why it matters: {of.get('why_it_matters', 'N/A')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    pdf.cell(20, 4, "", border=0, new_x=XPos.RIGHT, new_y=YPos.TOP)
                    pdf.cell(0, 4, clean_pdf_text(f"Recommendation: {of.get('suggestion')}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)
        pdf.ln(5)

    # Test Suggestions
    if test_suggestions:
        pdf.add_page()
        pdf.set_text_color(15, 23, 42)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, clean_pdf_text("Test Suggestions"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9.5)
        
        lines = test_suggestions.splitlines()
        for line in lines[:80]:
            if line.startswith("###"):
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 11)
                pdf.cell(0, 6, clean_pdf_text(line.replace("###", "").strip()), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_font("Helvetica", "", 9.5)
            elif line.strip().startswith("```"):
                pass
            else:
                if line.strip():
                    pdf.write(5, clean_pdf_text(line) + "\n")

    # Repo Health Analysis
    if repo_analysis:
        pdf.add_page()
        pdf.set_text_color(15, 23, 42)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, clean_pdf_text("Repository Health Analysis"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, clean_pdf_text(f"Repository Health Score: {repo_analysis.get('health_score', 0)}/100"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, clean_pdf_text(f"Source Files: {repo_analysis.get('source_files_count', 0)} | Test Files: {repo_analysis.get('test_files_count', 0)}"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, clean_pdf_text(f"Documentation Coverage Estimate: {repo_analysis.get('docstring_coverage', 0)}%"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, clean_pdf_text("Qualitative Analysis Summary"), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9.5)

        lines = repo_analysis.get("analysis_report", "").splitlines()
        for line in lines[:80]:
            if line.startswith("#") or line.startswith("##"):
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 10.5)
                pdf.cell(0, 6, clean_pdf_text(line.replace("#", "").strip()), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_font("Helvetica", "", 9.5)
            else:
                if line.strip():
                    pdf.write(5, clean_pdf_text(line) + "\n")

    pdf.output(output_filepath)
