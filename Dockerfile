FROM python:3.14-slim
WORKDIR /app
COPY legoname.py .
ENV PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8080
CMD ["python", "legoname.py"]
