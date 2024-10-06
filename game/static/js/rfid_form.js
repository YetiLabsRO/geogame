// Example POST method implementation:
async function postData(url = '', data = {}, csrf_token) {
    // Default options are marked with *
    const response = await fetch(url, {
        method: 'POST', // *GET, POST, PUT, DELETE, etc.
        mode: 'cors', // no-cors, *cors, same-origin
        cache: 'no-cache', // *default, no-cache, reload, force-cache, only-if-cached
        credentials: 'same-origin', // include, *same-origin, omit
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrf_token

            // 'Content-Type': 'application/x-www-form-urlencoded',
        },
        redirect: 'follow', // manual, *follow, error
        referrerPolicy: 'no-referrer', // no-referrer, *no-referrer-when-downgrade, origin, origin-when-cross-origin, same-origin, strict-origin, strict-origin-when-cross-origin, unsafe-url
        body: JSON.stringify(data) // body data type must match "Content-Type" header
    });
    return response.json(); // parses JSON response into native JavaScript objects
}

function getCookie(cname) {
    var name = cname + "=";
    var decodedCookie = decodeURIComponent(document.cookie);
    var ca = decodedCookie.split(';');
    for (var i = 0; i < ca.length; i++) {
        var c = ca[i];
        while (c.charAt(0) == ' ') {
            c = c.substring(1);
        }
        if (c.indexOf(name) == 0) {
            return c.substring(name.length, c.length);
        }
    }
    return "";
}

let form = document.getElementById("teamTowerChallengeForm")
if (form) {
    form.addEventListener("submit", function (e) {
        // let btn = document.getElementById(e.target.id);
        // btn.setAttribute("disabled", true);
        let form = document.getElementById("teamTowerChallengeForm");


        if (!form.checkValidity()) {
            // btn.setAttribute("disabled", false);
            console.log("invalid form");
            e.preventDefault();
            e.stopPropagation();
        }

        form.classList.add('was-validated')

        let data = {
            challenge: document.getElementById("challenge").value,
            team: document.getElementById("team").value,
            tower: document.getElementById("tower").value,
            lng: document.getElementById("lng").value,
            lat: document.getElementById("lat").value,
            response_text: document.getElementById("response_text").value,

        }

        photo_data = document.getElementById("file_base64").value;

        if (photo_data) {
            data['photo'] = photo_data;
        }


        // console.log(data);

        postData('/api/team_tower_challenges/', data, getCookie("csrftoken"))
            .then(data => {
                console.log(data); // JSON data parsed by `data.json()` call
                window.location.href = window.location.href;
            });

        e.preventDefault();
        e.stopPropagation();
    })
}



function getLocation() {
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(setPosition);
  } else {
    console.log("Location isn't supported in this browser!")
  }
}

function setPosition(position) {
    document.getElementById("lat").value = position.coords.latitude;
    document.getElementById("lng").value = position.coords.longitude;
}

getLocation();