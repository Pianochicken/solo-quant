#!/bin/bash
source .venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$(pwd)
streamlit run SoloQuant/ui/app.py
