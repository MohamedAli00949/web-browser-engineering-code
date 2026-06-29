
var count = 0;
function callback() {
  var output = document.querySelectorAll("div")[1];
  var content = "count: " + count;
  console.log(content);
  output.innerHTML = content;
  if (count < 100) {
    count += 1;
  }
}

requestAnimationFrame(callback);
