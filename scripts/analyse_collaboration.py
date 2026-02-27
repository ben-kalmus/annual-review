#!/usr/bin/env python3
"""
Analyze collaboration between two users based on PR reviews and JIRA tickets.
"""

import json
import argparse
from pathlib import Path


def analyze_pr_collaboration(user1_prs, user2_prs, user1_name, user2_name):
    """Find PRs where users reviewed each other's work."""
    
    # User2 reviewed User1's PRs
    user2_reviewed_user1 = []
    for pr in user1_prs:
        if pr.get('reviews'):
            for review in pr['reviews']:
                if review.get('author') == user2_name:
                    user2_reviewed_user1.append({
                        'number': pr['number'],
                        'title': pr['title'],
                        'repo': pr.get('repo', pr.get('repository', 'unknown')),
                        'url': pr['url'],
                        'state': review.get('state'),
                        'created': pr['createdAt'][:10],
                        'merged': pr.get('mergedAt', '')[:10] if pr.get('mergedAt') else None,
                        'additions': pr.get('additions', 0),
                        'deletions': pr.get('deletions', 0),
                    })
                    break
    
    # User1 reviewed User2's PRs
    user1_reviewed_user2 = []
    for pr in user2_prs:
        if pr.get('reviews'):
            for review in pr['reviews']:
                if review.get('author') == user1_name:
                    user1_reviewed_user2.append({
                        'number': pr['number'],
                        'title': pr['title'],
                        'repo': pr.get('repo', pr.get('repository', 'unknown')),
                        'url': pr['url'],
                        'state': review.get('state'),
                        'created': pr['createdAt'][:10],
                        'merged': pr.get('mergedAt', '')[:10] if pr.get('mergedAt') else None,
                        'additions': pr.get('additions', 0),
                        'deletions': pr.get('deletions', 0),
                    })
                    break
    
    return user2_reviewed_user1, user1_reviewed_user2


def categorize_prs(prs):
    """Categorize PRs by type based on title."""
    categories = {
        'test': [],
        'feat': [],
        'fix': [],
        'refactor': [],
        'docs': [],
        'chore': [],
        'other': []
    }
    
    for pr in prs:
        title = pr['title'].lower()
        categorized = False
        for cat in ['test', 'feat', 'fix', 'refactor', 'docs', 'chore']:
            if title.startswith(f'{cat}(') or title.startswith(f'{cat}:'):
                categories[cat].append(pr)
                categorized = True
                break
        if not categorized:
            categories['other'].append(pr)
    
    return categories


def main():
    parser = argparse.ArgumentParser(description='Analyze collaboration between two users')
    parser.add_argument('--user1', required=True, help='First user (e.g., ben-kalmus)')
    parser.add_argument('--user2', required=True, help='Second user (e.g., gavinwade12)')
    parser.add_argument('--limit', type=int, default=10, help='Number of examples to show per category')
    
    args = parser.parse_args()
    
    # Load PR data
    user1_prs_file = Path(f'data/{args.user1}_prs.json')
    user2_prs_file = Path(f'data/{args.user2}_prs.json')
    
    if not user1_prs_file.exists():
        print(f"Error: {user1_prs_file} not found")
        return
    if not user2_prs_file.exists():
        print(f"Error: {user2_prs_file} not found")
        return
    
    with open(user1_prs_file) as f:
        user1_prs = json.load(f)
    with open(user2_prs_file) as f:
        user2_prs = json.load(f)
    
    # Analyze collaboration
    user2_reviewed_user1, user1_reviewed_user2 = analyze_pr_collaboration(
        user1_prs, user2_prs, args.user1, args.user2
    )
    
    print(f"\n{'='*80}")
    print(f"  Collaboration Analysis — {args.user1} & {args.user2}")
    print(f"{'='*80}\n")
    
    print(f"── Review Summary ────────────────────────────────────")
    print(f"  {args.user2} reviewed {len(user2_reviewed_user1)} PRs by {args.user1}")
    print(f"  {args.user1} reviewed {len(user1_reviewed_user2)} PRs by {args.user2}")
    print()
    
    # Categorize user1's PRs that user2 reviewed
    print(f"── {args.user2} reviewed {args.user1}'s PRs ───────────────────")
    categories = categorize_prs(user2_reviewed_user1)
    
    for cat, prs in categories.items():
        if prs:
            print(f"\n{cat.upper()} ({len(prs)} PRs):")
            for pr in prs[-args.limit:]:
                size = pr['additions'] + pr['deletions']
                print(f"  [{pr['created']}] {pr['repo']}#{pr['number']} (+{pr['additions']}/-{pr['deletions']} lines)")
                print(f"    {pr['title']}")
                print(f"    {pr['url']}")
                print()
    
    # Show recent collaboration
    print(f"\n── Recent Collaboration ({args.limit} most recent) ──────────────")
    for pr in user2_reviewed_user1[-args.limit:]:
        print(f"  [{pr['created']}] {pr['repo']}#{pr['number']}")
        print(f"    {pr['title']}")
        print(f"    {pr['url']}")
        print()


if __name__ == '__main__':
    main()
