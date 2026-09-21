"""ESSCAN administration from the command line.

Your schema has exactly two roles, Professor and Student
(``models/user.py``, ``UserRole``). A real third "Admin" role would mean an
enum change, a MySQL migration on a live column, permission guards on every
router, and a whole frontend section -- days of work that competes directly
with the OCR accuracy you are trying to reach before your defense.

This does the jobs a super-admin account would actually be used for, without
touching the schema: create accounts, reset passwords, promote or demote,
list, and delete. It runs against the database directly, so it works even
when nobody can log in -- which is the situation an admin account exists for.

Run from backend/ with the venv active:

    python admin.py list
    python admin.py list --role Professor
    python admin.py create --email me@school.edu --password "..." --role Professor --first Ana --last Reyes
    python admin.py passwd --email me@school.edu --password "new-password"
    python admin.py promote --email someone@school.edu
    python admin.py demote  --email someone@school.edu
    python admin.py delete  --email someone@school.edu
    python admin.py whoami  --email someone@school.edu
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


def _bootstrap():
    try:
        from dotenv import load_dotenv
        env = Path(__file__).resolve().parent / ".env"
        if env.is_file():
            load_dotenv(env, override=False)
    except ImportError:
        pass
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _prompt_password() -> str:
    first = getpass.getpass("New password: ")
    if len(first) < 8:
        print("Use at least 8 characters.")
        sys.exit(1)
    if first != getpass.getpass("Confirm: "):
        print("Passwords did not match.")
        sys.exit(1)
    return first


def main() -> int:
    _bootstrap()

    ap = argparse.ArgumentParser(description="ESSCAN user administration.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="List accounts.")
    p.add_argument("--role", choices=["Professor", "Student", "Admin"])

    p = sub.add_parser("create", help="Create an account.")
    p.add_argument("--email", required=True)
    p.add_argument("--first", required=True)
    p.add_argument("--last", required=True)
    p.add_argument("--role", choices=["Professor", "Student", "Admin"], default="Professor")
    p.add_argument("--password", help="Omit to be prompted (does not appear in shell history).")

    p = sub.add_parser("passwd", help="Reset a password.")
    p.add_argument("--email", required=True)
    p.add_argument("--password")

    for name, helptext in (("promote", "Make a user a Professor."),
                           ("demote", "Make a user a Student."),
                           ("delete", "Delete a user."),
                           ("whoami", "Show one account and what it owns.")):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("--email", required=True)

    args = ap.parse_args()

    from database import SessionLocal
    from models.user import User, UserRole
    from services.auth_service import hash_password

    db = SessionLocal()
    try:
        if args.command == "list":
            q = db.query(User)
            if args.role:
                q = q.filter(User.role == UserRole(args.role))
            users = q.order_by(User.role, User.last_name).all()
            if not users:
                print("No accounts found.")
                return 0
            print(f"{'id':>5}  {'role':<10} {'name':<28} email")
            print("-" * 78)
            for u in users:
                role = u.role.value if hasattr(u.role, "value") else str(u.role)
                print(f"{u.user_id:>5}  {role:<10} "
                      f"{(u.first_name + ' ' + u.last_name)[:27]:<28} {u.email}")
            print(f"\n{len(users)} account(s).")
            return 0

        existing = db.query(User).filter(User.email == args.email).first()

        if args.command == "create":
            if existing:
                print(f"{args.email} already exists (id {existing.user_id}). "
                      f"Use 'passwd' to change its password.")
                return 1
            password = args.password or _prompt_password()
            if len(password) < 8:
                print("Use at least 8 characters.")
                return 1
            user = User(
                first_name=args.first, last_name=args.last, email=args.email,
                password_hash=hash_password(password), role=UserRole(args.role),
            )
            db.add(user)
            db.commit()
            print(f"Created {args.role} '{args.first} {args.last}' <{args.email}> "
                  f"as id {user.user_id}.")
            return 0

        if existing is None:
            print(f"No account with email {args.email}.")
            return 1

        if args.command == "passwd":
            password = args.password or _prompt_password()
            if len(password) < 8:
                print("Use at least 8 characters.")
                return 1
            existing.password_hash = hash_password(password)
            db.commit()
            print(f"Password reset for {args.email}.")
            return 0

        if args.command in ("promote", "demote"):
            target = UserRole.Professor if args.command == "promote" else UserRole.Student
            was = existing.role.value if hasattr(existing.role, "value") else str(existing.role)
            if was == target.value:
                print(f"{args.email} is already a {target.value}.")
                return 0
            existing.role = target
            db.commit()
            print(f"{args.email}: {was} -> {target.value}")
            print("They must log out and back in; the role is baked into their JWT.")
            return 0

        if args.command == "whoami":
            from models.class_model import Class
            from models.enrollment import Enrollment
            from models.exam_submission import ExamSubmission
            role = existing.role.value if hasattr(existing.role, "value") else str(existing.role)
            print(f"id      : {existing.user_id}")
            print(f"name    : {existing.first_name} {existing.last_name}")
            print(f"email   : {existing.email}")
            print(f"role    : {role}")
            print(f"created : {existing.created_at}")
            taught = db.query(Class).filter(Class.teacher_id == existing.user_id).count()
            enrolled = db.query(Enrollment).filter(
                Enrollment.student_id == existing.user_id).count()
            subs = db.query(ExamSubmission).filter(
                ExamSubmission.student_id == existing.user_id).count()
            print(f"classes taught   : {taught}")
            print(f"classes enrolled : {enrolled}")
            print(f"submissions      : {subs}")
            return 0

        if args.command == "delete":
            from models.class_model import Class
            taught = db.query(Class).filter(Class.teacher_id == existing.user_id).count()
            if taught:
                print(f"{args.email} still teaches {taught} class(es). Deleting would "
                      f"orphan their exams and every submission attached to them.")
                print("Reassign or delete those classes first.")
                return 1
            confirm = input(f"Delete {args.email} (id {existing.user_id})? Type the email to confirm: ")
            if confirm.strip() != args.email:
                print("Not confirmed, nothing deleted.")
                return 1
            db.delete(existing)
            db.commit()
            print(f"Deleted {args.email}.")
            return 0

        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
