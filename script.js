function downloadVideo() {

let url = document.getElementById("videoURL").value;

fetch("/api/download?url=" + encodeURIComponent(url))
.then(function(res){
return res.json();
})
.then(function(data){

document.getElementById("result").innerText = data.message + " : " + data.url;

})
.catch(function(error){
document.getElementById("result").innerText = "Error connecting API";
console.log(error);
});

}
