# -------------------------------------------------------------
# DEPRECATED MODULE
# -------------------------------------------------------------
#
# This file contained choose_tool(), a prototype that used the
# raw Groq API to select a filesystem tool from a description.
#
# It was replaced by agent.py, which uses LangChain's ChatGroq
# with bound tools and structured intent extraction functions
# (extract_rename_request, extract_move_request, run_agent).
#
# choose_tool() was never imported or called anywhere in the
# application. It has been removed to avoid confusion.
#
# If a new low-level Groq client is ever needed, add it here
# and import it explicitly where used.
#
# -------------------------------------------------------------
