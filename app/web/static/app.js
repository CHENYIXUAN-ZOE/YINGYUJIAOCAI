async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error?.message || "request failed");
  }
  return data;
}

const uploadForm = document.getElementById("upload-form");
if (uploadForm) {
  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fileInput = document.getElementById("pdf-file");
    const result = document.getElementById("upload-result");
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    try {
      const data = await requestJson(`${window.APP_CONFIG.apiPrefix}/upload`, {
        method: "POST",
        body: formData,
      });
      result.textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      result.textContent = error.message;
    }
  });
}

const jobStatus = document.getElementById("job-status");
if (jobStatus && window.APP_CONFIG.jobId) {
  requestJson(`${window.APP_CONFIG.apiPrefix}/jobs/${window.APP_CONFIG.jobId}`)
    .then((data) => {
      jobStatus.textContent = JSON.stringify(data, null, 2);
    })
    .catch((error) => {
      jobStatus.textContent = error.message;
    });
}

const resultData = document.getElementById("result-data");
if (resultData && window.APP_CONFIG.jobId) {
  requestJson(`${window.APP_CONFIG.apiPrefix}/results/${window.APP_CONFIG.jobId}`)
    .then((data) => {
      resultData.textContent = JSON.stringify(data, null, 2);
    })
    .catch((error) => {
      resultData.textContent = error.message;
    });
}
