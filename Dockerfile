# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the entire project context (respecting .dockerignore)
COPY . .

# Install the required packages from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# --- FIX for Unicode Error ---
# Remove the UTF-8 BOM (invisible characters) from the main script if it exists.
RUN sed -i '1s/^\xEF\xBB\xBF//' src/trusted_data_agent/main.py

# Install the application in editable mode to make the 'src' package discoverable
RUN pip install -e .

# Make port 5050 available to the world outside this container
EXPOSE 5050

# The command to run when the container launches
CMD ["python", "-m", "trusted_data_agent.main"]

