@echo off
@REM REM Placeholder file - Copy your holdflight/deploy.bat content here
@echo off
REM Website Analyzer - Google Cloud Run Deployment Script (Windows Batch)
REM Make sure you have gcloud CLI installed and authenticated

setlocal enabledelayedexpansion

# -- Load environment variables from .env file --

REM Load environment variables from .env file if it exists
REM Note: This is a simple parser - for complex .env files, consider using python-dotenv or similar
if exist .env (
    echo Loading environment variables from .env file...
    for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" (
            set "%%a=%%b"
        )
    )
)

REM Configuration
set PROJECT_ID=marketing-planner-c8f02
set SERVICE_NAME=website-analyzer
set REGION=us-central1
set REPOSITORY=website-analyzer-repo
set IMAGE_NAME=planner-image
# testing git push
REM Get OpenAI API key from environment variable (SECURITY: Never hardcode API keys!)
if "%OPENAI_API_KEY%"=="" (
    echo.
    echo WARNING: OPENAI_API_KEY environment variable is not set!
    echo Please add it to your .env file:
    echo OPENAI_API_KEY=your-api-key-here
    echo.
    echo Or set it before running this script:
    echo set OPENAI_API_KEY=your-api-key-here
    echo.
    pause
    exit /b 1
)


echo.
echo 🚀 Deploying Website Analyzer to Google Cloud Run
echo ==================================================
echo.

REM Check if gcloud is installed
gcloud --version >nul 2>&1
if errorlevel 1 (
    echo ❌ gcloud CLI is not installed. Please install it first.
    echo    Visit: https://cloud.google.com/sdk/docs/install
    pause
    exit /b 1
)

REM Check if Docker is installed
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker is not installed. Please install it first.
    echo    Visit: https://docs.docker.com/get-docker/
    pause
    exit /b 1
)

REM Prompt for project ID if not set
if "%PROJECT_ID%"=="your-gcp-project-id" (
    set /p PROJECT_ID="Enter your GCP Project ID: "
)

REM OpenAI API key is set, continuing with deployment

echo.
echo 📋 Project ID: %PROJECT_ID%
echo 🌍 Region: %REGION%
echo 🔑 OpenAI API Key: %OPENAI_API_KEY:~0,10%...
echo.

REM Set the project
echo 🔧 Setting GCP project...
gcloud config set project %PROJECT_ID%
if errorlevel 1 (
    echo ❌ Failed to set project. Please check your project ID.
    pause
    exit /b 1
)

REM Enable required APIs
echo 🔌 Enabling required APIs...
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com

REM Create Artifact Registry repository if it doesn't exist
echo 📦 Creating Artifact Registry repository...
gcloud artifacts repositories create %REPOSITORY% --repository-format=docker --location=%REGION% --description="Docker repository for Website Analyzer" 2>nul
if errorlevel 1 (
    echo Repository already exists or creation failed - continuing...
)

REM Build Docker image
echo 🏗️ Building Docker image...
docker build -t %IMAGE_NAME% .
if errorlevel 1 (
    echo ❌ Docker build failed. Check the logs above.
    pause
    exit /b 1
)

REM Tag the image for Google Container Registry
echo 🏷️ Tagging image for Google Container Registry...
docker tag %IMAGE_NAME% gcr.io/%PROJECT_ID%/%IMAGE_NAME%:latest
if errorlevel 1 (
    echo ❌ Docker tag failed. Check the logs above.
    pause
    exit /b 1
)

REM Configure Docker to use gcloud as a credential helper
echo 🔐 Configuring Docker authentication...
gcloud auth configure-docker
if errorlevel 1 (
    echo ❌ Docker authentication configuration failed.
    pause
    exit /b 1
)

REM Push the image to Google Container Registry
echo 📤 Pushing image to Google Container Registry...
docker push gcr.io/%PROJECT_ID%/%IMAGE_NAME%:latest
if errorlevel 1 (
    echo ❌ Docker push failed. Check the logs above.
    pause
    exit /b 1
)

REM Deploy to Cloud Run
echo 🚀 Deploying to Cloud Run...
gcloud run deploy %SERVICE_NAME% --image gcr.io/%PROJECT_ID%/%IMAGE_NAME%:latest --region=%REGION% --platform=managed --allow-unauthenticated --set-env-vars OPENAI_API_KEY="%OPENAI_API_KEY%" --port=8080 --memory=2Gi --cpu=2 --timeout=300 --max-instances=10
if errorlevel 1 (
    echo ❌ Cloud Run deployment failed. Check the logs above.
    pause
    exit /b 1
)

REM Get the service URL
echo 🌐 Getting service URL...
for /f "tokens=*" %%i in ('gcloud run services describe %SERVICE_NAME% --region=%REGION% --format="value(status.url)"') do set SERVICE_URL=%%i

echo.
echo ✅ Deployment completed successfully!
echo 🔗 Your Website Analyzer is available at: %SERVICE_URL%
echo.
echo 📝 Next steps:
echo    1. Visit the URL above to use the web interface
echo    2. Test the API endpoint: %SERVICE_URL%/analyze
echo    3. Monitor logs: gcloud logs tail --service=%SERVICE_NAME%
echo.
echo Press any key to exit...
pause >nul



