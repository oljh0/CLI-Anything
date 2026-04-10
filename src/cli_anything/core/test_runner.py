"""测试运行器：集成 pytest，收集结果并生成报告"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TestReport:
    """测试运行报告"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration: float = 0.0
    exit_code: int = 0
    output: str = ""
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration": round(self.duration, 2),
            "exit_code": self.exit_code,
            "details": self.details,
        }

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.errors == 0


def run_tests(
    test_path: str = "tests/",
    work_dir: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
    timeout: int = 300,
) -> TestReport:
    """运行 pytest 并收集结果

    Args:
        test_path: 测试文件/目录路径
        work_dir: 工作目录（默认当前目录）
        extra_args: 额外 pytest 参数
        timeout: 超时秒数

    Returns:
        TestReport 测试报告
    """
    report = TestReport()
    cwd = work_dir or "."

    # 使用临时文件接收 JSON 报告
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w"
    ) as tmp:
        json_path = tmp.name

    # 构造 pytest 命令
    cmd = [
        sys.executable, "-m", "pytest",
        test_path,
        "-v",
        "--tb=short",
        f"--json-report-file={json_path}",
        "--json-report",
    ]
    if extra_args:
        cmd.extend(extra_args)

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        report.duration = time.time() - start
        report.exit_code = result.returncode
        report.output = result.stdout + result.stderr

        # 尝试解析 JSON 报告
        json_file = Path(json_path)
        if json_file.exists():
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                summary = data.get("summary", {})
                report.total = summary.get("total", 0)
                report.passed = summary.get("passed", 0)
                report.failed = summary.get("failed", 0)
                report.errors = summary.get("error", 0)
                report.skipped = summary.get("skipped", 0)
                report.duration = data.get("duration", report.duration)

                # 提取失败用例详情
                for test in data.get("tests", []):
                    if test.get("outcome") in ("failed", "error"):
                        report.details.append({
                            "name": test.get("nodeid", ""),
                            "outcome": test.get("outcome", ""),
                            "message": test.get("call", {}).get("longrepr", ""),
                        })
            except (json.JSONDecodeError, KeyError):
                pass
        else:
            # JSON 报告插件不可用时，从 exit code 推断
            _parse_output_fallback(report, result)

    except subprocess.TimeoutExpired:
        report.duration = time.time() - start
        report.exit_code = -1
        report.output = f"测试超时（{timeout}秒）"

    finally:
        # 清理临时文件
        try:
            Path(json_path).unlink(missing_ok=True)
        except OSError:
            pass

    return report


def _parse_output_fallback(report: TestReport, result: subprocess.CompletedProcess):
    """从 pytest 标准输出解析结果（当 JSON 插件不可用时）"""
    output = result.stdout or ""
    # 找最后一行摘要，如 "5 passed, 2 failed in 1.23s"
    for line in reversed(output.splitlines()):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            import re
            for match in re.finditer(r"(\d+)\s+(passed|failed|error|skipped|warnings?)", line):
                count = int(match.group(1))
                kind = match.group(2)
                if kind == "passed":
                    report.passed = count
                elif kind == "failed":
                    report.failed = count
                elif kind == "error":
                    report.errors = count
                elif kind == "skipped":
                    report.skipped = count
            report.total = report.passed + report.failed + report.errors + report.skipped
            # 提取耗时
            dur_match = re.search(r"in\s+([\d.]+)s", line)
            if dur_match:
                report.duration = float(dur_match.group(1))
            break


def run_tests_simple(
    test_path: str = "tests/",
    work_dir: Optional[str] = None,
    timeout: int = 300,
) -> TestReport:
    """简化版测试运行（不依赖 json-report 插件）"""
    report = TestReport()
    cwd = work_dir or "."

    cmd = [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"]

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout,
        )
        report.duration = time.time() - start
        report.exit_code = result.returncode
        report.output = result.stdout + result.stderr
        _parse_output_fallback(report, result)
    except subprocess.TimeoutExpired:
        report.duration = time.time() - start
        report.exit_code = -1
        report.output = f"测试超时（{timeout}秒）"

    return report
