let button = document.getElementById("rules")
button.addEventListener("click", function (e) {
    window.location.href = "/rules/";
})

let map = L.map('map').setView([46.068374, 23.571797], 17);

L.tileLayer('https://api.mapbox.com/styles/v1/{id}/tiles/{z}/{x}/{y}?access_token={accessToken}', {
    attribution: 'Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, Imagery © <a href="https://www.mapbox.com/">Mapbox</a>',
    maxZoom: 18,
    id: 'mapbox/streets-v11',
    tileSize: 512,
    zoomOffset: -1,
    accessToken: 'pk.eyJ1IjoieWV0aWJhbGF1cnUiLCJhIjoiY2tqMnl6cWZwNWJ0aDJycWo4ZG41YjNtciJ9.IkhU0PgtFeEYaslj78WO1A'
}).addTo(map);

function create_zones(data) {
    data.forEach(function (e) {
        if (e.shape) {
            //  remove last point
            e.shape.coordinates[0].splice(-1, 1);

            // switch lat / long
            let shape = [];
            e.shape.coordinates[0].forEach(function (longlat) {
               shape.push([longlat[1], longlat[0]])
            });

            L.polygon(shape, {color: e.color}).addTo(map);
        }
    });
}

function create_towers(data) {
    data.forEach(function(e) {
        L.marker([e.location.coordinates[1], e.location.coordinates[0]]).addTo(map);
    })
}
fetch("/api/zones/").then(response => response.json()).then(data => create_zones(data));
fetch("/api/towers/").then(response => response.json()).then(data => create_towers(data));

