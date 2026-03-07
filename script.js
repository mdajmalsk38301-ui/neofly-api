function downloadVideo(){

let url=document.getElementById("videoURL").value

fetch("/download?url="+encodeURIComponent(url))

.then(res=>res.json())

.then(data=>{

console.log(data)

})

}
