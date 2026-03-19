#!/usr/bin/env python3
"""
批量验证 worktree 的 Maven 可执行性（compile + test）。

功能：
1. 从 worktree_records.csv/xlsx 读取任务；
2. 对每个 worktree 运行 `mvn compile` 与 `mvn test`；
3. 输出逐任务结果 JSON；
4. 回写 records 文件中的 compile_success / test_success / evaluated_at / notes。
"""

import os
import json
import argparse
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量执行 worktree 的 mvn compile/test 验证"
    )
    parser.add_argument(
        "--records",
        "-r",
        required=True,
        help="worktree_records.csv 或 worktree_records.xlsx 路径"
    )
    parser.add_argument(
        "--status",
        nargs="+",
        default=["ready"],
        help="只处理这些状态（默认: ready）"
    )
    parser.add_argument("--projects", "-p", nargs="+", help="只处理指定项目")
    parser.add_argument("--types", "-t", nargs="+", help="只处理指定类型")
    parser.add_argument("--limit", "-l", type=int, help="最多处理 N 条")
    parser.add_argument("--workers", "-w", type=int, default=2, help="并发 worker 数")
    parser.add_argument(
        "--maven-cmd",
        default="mvn",
        help="Maven 可执行文件（默认: mvn）"
    )
    parser.add_argument(
        "--maven-repo-local",
        default=None,
        help="可选：指定本地 Maven 仓库路径（不指定则使用 Maven 默认 ~/.m2/repository）"
    )
    parser.add_argument(
        "--maven-extra-args",
        default="",
        help="额外 Maven 参数（例如: -DskipITs）"
    )
    parser.add_argument(
        "--prewarm-only",
        action="store_true",
        help="仅预热依赖仓库（dependency:go-offline），不执行 compile/test"
    )
    parser.add_argument(
        "--compile-timeout",
        type=int,
        default=300,
        help="compile 超时秒数（默认: 300）"
    )
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=900,
        help="test 超时秒数（默认: 900）"
    )
    parser.add_argument(
        "--java-home",
        default=None,
        help="可选 JAVA_HOME"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="结果 JSON 输出路径（默认: records 同目录下 verify_maven_results.json）"
    )
    parser.add_argument(
        "--no-write-back",
        action="store_true",
        help="不回写 records 文件"
    )
    return parser.parse_args()


def load_records(path: str) -> pd.DataFrame:
    if path.endswith(".xlsx") or path.endswith(".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def save_records(df: pd.DataFrame, path: str):
    if path.endswith(".xlsx") or path.endswith(".xls"):
        df.to_excel(path, index=False)
    else:
        df.to_csv(path, index=False)


def _run_cmd(
    cmd: List[str],
    cwd: str,
    timeout: int,
    java_home: str = None,
) -> Dict[str, Any]:
    env = os.environ.copy()
    if java_home:
        env["JAVA_HOME"] = java_home
        env["PATH"] = f"{java_home}/bin:{env.get('PATH', '')}"

    started_at = datetime.now().isoformat()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "success": proc.returncode == 0,
            "return_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "error": None,
            "started_at": started_at,
            "ended_at": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "return_code": -1,
            "stdout": e.stdout or "",
            "stderr": e.stderr or "",
            "error": f"Timeout after {timeout}s",
            "started_at": started_at,
            "ended_at": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": "",
            "error": str(e),
            "started_at": started_at,
            "ended_at": datetime.now().isoformat(),
        }


def verify_one(
    record: Dict[str, Any],
    args: argparse.Namespace,
    logs_dir: str,
) -> Dict[str, Any]:
    task_id = int(record.get("task_id"))
    worktree_path = str(record.get("worktree_path", "")).strip()
    project = str(record.get("project", "")).strip()

    result = {
        "task_id": task_id,
        "project": project,
        "worktree_path": worktree_path,
        "compile_success": False,
        "test_success": False,
        "success": False,
        "error": None,
        "compile": {},
        "test": {},
    }

    if not worktree_path or not os.path.isdir(worktree_path):
        result["error"] = f"worktree 不存在: {worktree_path}"
        return result

    pom_path = os.path.join(worktree_path, "pom.xml")
    if not os.path.exists(pom_path):
        result["error"] = f"pom.xml 不存在: {pom_path}"
        return result

    repo_local = None
    if args.maven_repo_local:
        repo_local = args.maven_repo_local
        if not os.path.isabs(repo_local):
            repo_local = os.path.join(worktree_path, repo_local)
        os.makedirs(repo_local, exist_ok=True)

    common_flags = [
        "-Drat.skip=true",
        "-Denforcer.skip=true",
        "-Dcheckstyle.skip=true",
        "-Dmaven.javadoc.skip=true",
        "-DfailIfNoTests=false",
        "-B",
        "-q",
    ]
    if repo_local:
        common_flags.insert(0, f"-Dmaven.repo.local={repo_local}")
    extra = args.maven_extra_args.split() if args.maven_extra_args.strip() else []

    prewarm_cmd = [args.maven_cmd, "dependency:go-offline", "-DskipTests"] + common_flags + extra
    prewarm_res = _run_cmd(
        prewarm_cmd,
        worktree_path,
        timeout=args.compile_timeout,
        java_home=args.java_home,
    )
    result["prewarm"] = prewarm_res

    prewarm_log = os.path.join(logs_dir, f"task_{task_id:03d}_prewarm.log")
    with open(prewarm_log, "w", encoding="utf-8") as f:
        f.write(f"CMD: {' '.join(prewarm_cmd)}\n")
        f.write(f"CWD: {worktree_path}\n")
        f.write(f"SUCCESS: {prewarm_res['success']}\n")
        f.write(f"RETURN_CODE: {prewarm_res['return_code']}\n\n")
        f.write("=== STDOUT ===\n")
        f.write(prewarm_res.get("stdout", ""))
        f.write("\n=== STDERR ===\n")
        f.write(prewarm_res.get("stderr", ""))
        if prewarm_res.get("error"):
            f.write(f"\n=== ERROR ===\n{prewarm_res['error']}\n")

    if args.prewarm_only:
        result["compile_success"] = bool(prewarm_res.get("success"))
        result["test_success"] = bool(prewarm_res.get("success"))
        result["success"] = bool(prewarm_res.get("success"))
        if not result["success"]:
            result["error"] = prewarm_res.get("error") or "prewarm failed"
        return result

    compile_cmd = [args.maven_cmd, "compile", "-DskipTests"] + common_flags + extra
    compile_res = _run_cmd(
        compile_cmd,
        worktree_path,
        timeout=args.compile_timeout,
        java_home=args.java_home,
    )
    result["compile"] = compile_res
    result["compile_success"] = bool(compile_res.get("success"))

    compile_log = os.path.join(logs_dir, f"task_{task_id:03d}_compile.log")
    with open(compile_log, "w", encoding="utf-8") as f:
        f.write(f"CMD: {' '.join(compile_cmd)}\n")
        f.write(f"CWD: {worktree_path}\n")
        f.write(f"SUCCESS: {compile_res['success']}\n")
        f.write(f"RETURN_CODE: {compile_res['return_code']}\n\n")
        f.write("=== STDOUT ===\n")
        f.write(compile_res.get("stdout", ""))
        f.write("\n=== STDERR ===\n")
        f.write(compile_res.get("stderr", ""))
        if compile_res.get("error"):
            f.write(f"\n=== ERROR ===\n{compile_res['error']}\n")

    if not result["compile_success"]:
        result["error"] = compile_res.get("error") or "compile failed"
        return result

    test_cmd = [args.maven_cmd, "test"] + common_flags + extra
    test_res = _run_cmd(
        test_cmd,
        worktree_path,
        timeout=args.test_timeout,
        java_home=args.java_home,
    )
    result["test"] = test_res
    result["test_success"] = bool(test_res.get("success"))
    result["success"] = result["compile_success"] and result["test_success"]
    if not result["test_success"]:
        result["error"] = test_res.get("error") or "test failed"

    test_log = os.path.join(logs_dir, f"task_{task_id:03d}_test.log")
    with open(test_log, "w", encoding="utf-8") as f:
        f.write(f"CMD: {' '.join(test_cmd)}\n")
        f.write(f"CWD: {worktree_path}\n")
        f.write(f"SUCCESS: {test_res['success']}\n")
        f.write(f"RETURN_CODE: {test_res['return_code']}\n\n")
        f.write("=== STDOUT ===\n")
        f.write(test_res.get("stdout", ""))
        f.write("\n=== STDERR ===\n")
        f.write(test_res.get("stderr", ""))
        if test_res.get("error"):
            f.write(f"\n=== ERROR ===\n{test_res['error']}\n")

    return result


def main() -> int:
    args = parse_args()
    df = load_records(args.records)

    if "task_id" not in df.columns:
        print("records 缺少 task_id 列")
        return 1

    if args.status and "status" in df.columns:
        df = df[df["status"].isin(args.status)]
    if args.projects and "project" in df.columns:
        df = df[df["project"].isin(args.projects)]
    if args.types and "type" in df.columns:
        df = df[df["type"].isin(args.types)]
    if args.limit:
        df = df.head(args.limit)

    if len(df) == 0:
        print("没有可处理的记录")
        return 0

    output_json = args.output
    if not output_json:
        output_json = os.path.join(
            os.path.dirname(os.path.abspath(args.records)),
            "verify_maven_results.json",
        )
    logs_dir = os.path.join(os.path.dirname(output_json), "verify_maven_logs")
    os.makedirs(logs_dir, exist_ok=True)

    tasks = [row.to_dict() for _, row in df.iterrows()]
    print(f"待验证任务: {len(tasks)} (workers={args.workers})")
    if args.maven_repo_local:
        print(f"本地 Maven 仓库: {args.maven_repo_local}")
    else:
        print("本地 Maven 仓库: 默认 (~/.m2/repository)")

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(verify_one, t, args, logs_dir): t for t in tasks}
        done = 0
        total = len(futs)
        for fut in as_completed(futs):
            done += 1
            r = fut.result()
            results.append(r)
            status = "OK" if r["success"] else "FAIL"
            print(f"[{done}/{total}] task {r['task_id']}: {status}")

    success = sum(1 for r in results if r["success"])
    compile_ok = sum(1 for r in results if r["compile_success"])
    test_ok = sum(1 for r in results if r["test_success"])

    payload = {
        "metadata": {
            "records": args.records,
            "timestamp": datetime.now().isoformat(),
            "total": len(results),
            "compile_success": compile_ok,
            "test_success": test_ok,
            "all_success": success,
            "logs_dir": logs_dir,
            "maven_repo_local": args.maven_repo_local or "~/.m2/repository (default)",
        },
        "results": sorted(results, key=lambda x: x["task_id"]),
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if not args.no_write_back:
        back = load_records(args.records)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        idx_col = back["task_id"].astype(int)
        for r in results:
            mask = idx_col == int(r["task_id"])
            if not mask.any():
                continue
            back.loc[mask, "compile_success"] = bool(r["compile_success"])
            back.loc[mask, "test_success"] = bool(r["test_success"])
            back.loc[mask, "evaluated_at"] = now
            note = "verify_maven:ok" if r["success"] else f"verify_maven:fail:{r.get('error', '')}"
            back.loc[mask, "notes"] = note[:500]
        save_records(back, args.records)

    print("\n========== 验证完成 ==========")
    print(f"总数: {len(results)}")
    print(f"compile 成功: {compile_ok}")
    print(f"test 成功: {test_ok}")
    print(f"compile+test 全成功: {success}")
    print(f"结果文件: {output_json}")
    print(f"日志目录: {logs_dir}")

    return 0 if success == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
