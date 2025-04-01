FROM python:3-slim
WORKDIR /app
COPY Pipfile ./
RUN pip install --no-cache-dir pipenv && pipenv install
COPY *.py ./
CMD [ "pipenv", "run", "python3", "-O", "-u", "main.py" ]