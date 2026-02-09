const express = require("express");
const client = require("prom-client");

const app = express();
const port = 8080;

// Collect default Node.js metrics (CPU, memory, event loop, GC)
client.collectDefaultMetrics();

// Custom metrics
const httpRequestCounter = new client.Counter({
  name: "http_requests_total",
  help: "Total number of HTTP requests",
  labelNames: ["method", "route", "status"]
});

const httpRequestDuration = new client.Histogram({
  name: "http_request_duration_seconds",
  help: "HTTP request latency",
  labelNames: ["method", "route", "status"],
  buckets: [0.1, 0.3, 0.5, 1, 1.5, 2, 5]
});

// Middleware to record metrics
app.use((req, res, next) => {
  const end = httpRequestDuration.startTimer({
    method: req.method,
    route: req.path
  });

  res.on("finish", () => {
    httpRequestCounter.inc({
      method: req.method,
      route: req.path,
      status: res.statusCode
    });
    end({ status: res.statusCode });
  });

  next();
});

// App endpoint
app.get("/", (req, res) => {
  res.send("Hello from JS app");
});

// Metrics endpoint
app.get("/metrics", async (req, res) => {
  res.set("Content-Type", client.register.contentType);
  res.end(await client.register.metrics());
});

// Start server
app.listen(port, () => {
  console.log(`JS app listening on port ${port}`);
});
