const regex = /v\d\.\d{1,2}\.\d{1,2}\w/gm;
let title = $(document).find("title").text();
let version = title.match(regex)[0].substring(1,);

let div = "<div></div><div id=\"korisversion\"><h3>latest koris: <a href=\"https://gitlab.noris.net/PI/koris/tags/v" + version + "\">" + version + "</a></h3><div>"


$( document ).ready(function() {
    console.log( "ready!" );
    $(".sphinxsidebarwrapper").append(div);
});
