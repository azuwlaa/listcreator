# List Creator - Telegram Bot

**List Creator** is a Telegram bot to create, manage, and share lists. Admins can control who can add, edit, or remove list items.

## Features

- Create new lists with `/newlist <name>`  
- Select/unselect lists (`/select`, `/unselect`)  
- Add, remove, or edit lines (`/addline`, `/rmline`, `/editline`)  
- Control whether members can add lines (`/listtype on/off`)  
- View all lists (`/lists`) or a specific list (`/list <name>`)

## Admins

Admins have full control over lists. Add your Telegram user IDs in `main.py` under the `ADMINS` set.

## Installation

1. Clone the repository:

```bash
git clone <repo_url>
cd ListCreator
