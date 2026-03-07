function downloadVideo(){

let url = document.getElementById("videoURL").value;

fetch("/download?url=" + encodeURIComponent(url))
.then(res => res.json())
.then(data => {

document.getElementById("result").innerText = JSON.stringify(data);

})
.catch(error => {
console.error(error);
});

}
