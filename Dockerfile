# Use the official AWS Lambda Python 3.12 runtime base image
FROM public.ecr.aws/lambda/python:3.12

# Copy your application code into the Lambda task root.
# AWS Lambda expects the code in ${LAMBDA_TASK_ROOT}
COPY lambda_function.py ${LAMBDA_TASK_ROOT}
COPY src/best_gbdt_model_now.pt ${LAMBDA_TASK_ROOT}
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# 1) Install CPU-only PyTorch first (no CUDA deps)
# 2) Then install the rest of your requirements into the task root
RUN pip install --no-cache-dir \
      torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
      numpy==2.2.2 -r requirements.txt -t ${LAMBDA_TASK_ROOT}

# Specify the Lambda handler in the format: file_name.function_name.
# Here, it refers to lambda_function.py with the lambda_handler() function.
CMD ["lambda_function.lambda_handler"]
