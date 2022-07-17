# test-looper
A rewrite of TestLooper, the statistical CI


### Spinning up the TL UI (cells interface) ###

Below is a walkthough to get the current [cells UI](./test_looper/cells.py) up and running.

Install ODB and make sure to build the bundle in `object_database/object_database/web/content` by running `npm install && npm run build` (in a nodeenv preferrably). 

Boot up ODB:
```
object_database_service_manager \
        localhost \
        localhost \
        8000 \
        Master \
        --run_db \
        --service-token TOKEN \
        --source ./odb/source \
        --storage ./odb/storage
```

In another environment install, configure and startup the 'active web service' like so:
```
# export our special Object Database token
export ODB_AUTH_TOKEN=TOKEN

# install the ActiveWebService
object_database_service_config install \
--class object_database.web.ActiveWebService.ActiveWebService \
--placement Master

# configure ActiveWebService
object_database_service_config configure ActiveWebService \
--port 8080 --hostname localhost --internal-port 8081

# check to make sure it is listed
object_database_service_config list

# start it up
object_database_service_config start ActiveWebService

# check to see that it is running
object_database_service_config instances
```

At this point you should be able to head to [http://localhost:8080/](http://localhost:8080/) and see the service running. 

Start up the TL odb service by running `cd ./test_looper && python odb.py` (you should see print statements in the ODB service window appearing). 

Install and start the TL service:

``` 
object_database_service_config install --class test_looper.cells.TLService --placement Master
object_database_service_config start TLService
```

You should now see the service in the services UI. Clicking on it will take you to TL. 

Note: if you want to make changes to the code, you will need to run the install command above. If you get an error telling you the service is "locked," go to the UI and click the locked icon to release it. Then you can install. 
