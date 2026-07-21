"""Deployment-local administrative commands."""

from __future__ import annotations

import argparse
import asyncio
import getpass

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import hash_password
from app.models.models import User


async def reset_password(username: str) -> int:
    """Interactively reset one password and revoke all existing JWTs."""
    password = getpass.getpass("New password (at least 12 characters): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 2
    if len(password) < 12:
        print("Password must contain at least 12 characters.")
        return 2
    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"User does not exist: {username}")
            return 1
        user.password_hash = hash_password(password)
        user.auth_version += 1
        await session.commit()
    print(f"Password reset completed for {username}; existing sessions were revoked.")
    return 0


async def list_users() -> int:
    """List operator identities without returning password material."""
    async with async_session_factory() as session:
        users = list((await session.scalars(select(User).order_by(User.username))).all())
    if not users:
        print("No users have been initialized.")
        return 0
    for user in users:
        print(f"{user.username}\t{user.role}\t{user.display_name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RobotsSystem local administration")
    commands = parser.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset-password", help="interactively reset an operator password")
    reset.add_argument("username")
    commands.add_parser("list-users", help="list configured operator accounts")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "reset-password":
        return asyncio.run(reset_password(args.username))
    if args.command == "list-users":
        return asyncio.run(list_users())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
