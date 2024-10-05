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
               shape.push([longlat[1], longlat[0]]);
            });

            L.polygon(shape, {color: e.color}).addTo(map);
        }
    });
}

let towers = {}
function create_towers(data) {
    data.forEach(function(e) {
        towers[e.id] = e
        L.marker([e.location.coordinates[1], e.location.coordinates[0]], {"title": e.name}).addTo(map);
    })
}
fetch("/api/towers/").then(response => response.json()).then(data => create_towers(data));

function show_options(data, e) {
    let tower_list = "<ul>";
    data.forEach(function(tower) {
        console.log(tower);
        tower_list += "<li><a href='/tower/" + tower.id + "/?lat=" + e.latlng['lat'] + "&lng=" + e.latlng['lng'] + "'>" + tower.name + "</a></li>";
    })
    tower_list += "</ul>";

    if (data.length) {
        L.marker(e.latlng).addTo(map).bindPopup("Poți face provocări pentru: " + tower_list).openPopup();
    } else {
        L.marker(e.latlng).addTo(map).bindPopup("Pare că nu ai niciun punct strategic în 50m de tine. Ți-ai pornit localizarea la telefon?").openPopup();
    }
    L.circle(e.latlng, Math.min(e.accuracy, 50)).addTo(map);
}

function onLocationFound(e) {
    //  make a call to get towers by their closest location to you
    console.log("location", e);
    let geo_url = "/api/towers/?lat=" + e.latlng['lat'] + "&lng=" + e.latlng['lng'] + "&accuracy=" + e.accuracy;
    fetch(geo_url).then(response => response.json()).then(data => show_options(data, e));
}

map.on('locationfound', onLocationFound);

function onLocationError(e) {
    alert(e.message);
}

map.on('locationerror', onLocationError);
map.locate({setView: true, maxZoom: 17});
