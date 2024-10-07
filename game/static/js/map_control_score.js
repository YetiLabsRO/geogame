let buttonRules = document.getElementById("rules")
buttonRules.addEventListener("click", function (e) {
    window.location.href = "/rules/";
})

let buttonLocation = document.getElementById("challenge")
buttonLocation.addEventListener("click", function (e) {
    window.location.href = "/tower/challenge/"
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

var redIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

var blueIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});


zones = [];
towers = [];

function create_zones(data) {
    zones.forEach(function(e) {
        e.remove()
    });

    zones = []
    data.forEach(function (e) {
        //  remove last point
        e.shape.coordinates[0].splice(-1, 1);

        // switch lat / long
        let shape = [];
        e.shape.coordinates[0].forEach(function (longlat) {
           shape.push([longlat[1], longlat[0]])
        });

        let poly = L.polygon(shape, {color: e.team_color})
        zones.push(poly);
        poly.addTo(map);
    });
}

function create_towers(data) {
    data.forEach(function(e) {
        let tower = L.marker(
            [e.location.coordinates[1], e.location.coordinates[0]],
            {
                "title": e.name,
                "icon": e.has_initial_bonus ? redIcon : blueIcon
            });
        towers.push(tower);
        tower.addTo(map);
    })
}

let teams = []
function update_teams(data) {
    teams = [];
    document.getElementById("scores").innerHTML = "";
    data = data.sort((a, b) => (a.current_score < b.current_score) ? 1 : -1);
    let score_list = "<ol>";


    data.forEach(function (e) {
        teams.push(e);

        score_list += "<li style='color: " + e.color + "'>" + e.name + ": " + e.current_score + "</li>";

    })
    score_list += "</ol>"
    document.getElementById("scores").innerHTML = score_list;
}

let group = document.getElementById("team-group");
let teamGroup = group.dataset.teamGroup;

fetch("/api/zones/?group=" + teamGroup).then(response => response.json()).then(data => create_zones(data));
fetch("/api/towers/").then(response => response.json()).then(data => create_towers(data));
fetch("/api/teams/?group=" + teamGroup).then(response => response.json()).then(data => update_teams(data));
let teams_intervel = setInterval(function () {
    fetch("/api/teams/?group=" + teamGroup).then(response => response.json()).then(data => update_teams(data));
    fetch("/api/zones/?group=" + teamGroup).then(response => response.json()).then(data => create_zones(data));
}, 5000);
