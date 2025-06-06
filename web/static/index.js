function deleteCoin(coinId) {
  fetch("/delete-coin", {
    method: "POST",
    body: JSON.stringify({ coinId: coinId }),
  }).then((_res) => {
    window.location.href = "/";
  });
}

function runStrategy(coinId) {
  fetch("/run-strategy", {
    method: "POST",
    body: JSON.stringify({ coinId: coinId }),
  }).then((_res) => {
    window.location.href = "/";
    setTimeout(timer, 15000);
  });
}

function stopStrategy(coinId) {
  fetch("/stop-strategy", {
    method: "POST",
    body: JSON.stringify({ coinId: coinId }),
  }).then((_res) => {
    window.location.href = "/";
  });
}

function loopStrategy(coinId) {
  fetch("/loop-strategy", {
    method: "POST",
    body: JSON.stringify({}),
  }).then((_res) => {
    window.location.href = "/";
  });
}