#!/usr/bin/env python3
"""
One-time script to generate deterministic user and hacker data files.

Uses Faker with a fixed seed so re-running always produces identical output.
Output: data/users.json and data/hackers.json
"""

import json
import os
from faker import Faker

SEED = 42
NUM_USERS = 500
NUM_HACKERS = 250

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def generate_users(fake: Faker) -> list[dict]:
    users = []
    for i in range(1, NUM_USERS + 1):
        users.append({"user_id": i, "name": fake.name()})
    return users


def generate_hackers(fake: Faker) -> list[dict]:
    hackers = []
    for i in range(1, NUM_HACKERS + 1):
        hackers.append(
            {
                "hacker_id": i,
                "name": fake.user_name(),
                "signature_seed": f"hacker_seed_{i}",
            }
        )
    return hackers


def main():
    fake = Faker()
    Faker.seed(SEED)

    os.makedirs(DATA_DIR, exist_ok=True)

    users = generate_users(fake)
    users_path = os.path.join(DATA_DIR, "users.json")
    with open(users_path, "w") as f:
        json.dump(users, f, indent=2)
    print(f"Generated {len(users)} users -> {users_path}")

    hackers = generate_hackers(fake)
    hackers_path = os.path.join(DATA_DIR, "hackers.json")
    with open(hackers_path, "w") as f:
        json.dump(hackers, f, indent=2)
    print(f"Generated {len(hackers)} hackers -> {hackers_path}")


if __name__ == "__main__":
    main()
