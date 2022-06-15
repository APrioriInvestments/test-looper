FROM python:3.9-slim
WORKDIR /code
ENV TEST_LOOPER_ROOT=$WORKDIR
ENV PYTHONPATH=$WORKDIR
COPY setup.py setup.py 
COPY requirements.txt requirements.txt
RUN pip install -e .
EXPOSE 8000
COPY . .
CMD ["python", "main.py"]