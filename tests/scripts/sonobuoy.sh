#!/bin/bash
echo "Downloading sonobuoy to check for compliance with kubernetes certification requirements from ${SONOBUOY_URL}";
curl -s -L -o sonobuoy.tgz ${SONOBUOY_URL};
tar --skip-old-files -x -z -f sonobuoy.tgz;
echo "Running sonobuoy on the cluster. This can take a very long time (up to 3 hours and more!)...";
if ! ./sonobuoy --kubeconfig ${KUBECONFIG} run; then echo "Failed to run sonobuoy!"; exit 1; fi

STARTTIME=`date +%s`;
echo "Starttime: `date`";
echo -n "Waiting for result to come in, checking every 5 minutes ";
while true; do
    sleep 300;
    echo -n ".";
    CURRTIME=`date +%s`;
    CURRELAPSED=$(( CURRTIME - STARTTIME));
    if [ ${CURRELAPSED} -ge ${SONOBUOY_CHECK_TIMEOUT_SECONDS} ]; then
        echo -e "\nMaximum alloted time for sonobuoy of ${SONOBUOY_CHECK_TIMEOUT_SECONDS} seconds to complete elapsed without result :[";
        exit 1;
    fi;
    SONOBUOY_CURR_STATUS=`./sonobuoy --kubeconfig ${KUBECONFIG} status`;
    if [ $? -ne 0 ]; then
        echo "Failed to check sonobuoy status!";
        exit 1;
    fi;
    echo ${SONOBUOY_CURR_STATUS} | grep "${SONOBUOY_COMPLETED_INDICATOR}" > /dev/null;
    if [ $? -eq 0 ]; then
        echo -e "\nResults are in! Retrieving and displaying for e2e tests...";
        until ./sonobuoy --kubeconfig ${KUBECONFIG} retrieve .; do sleep 10; done
        RESULTFILE=`ls | grep *sonobuoy*.tar.gz`;
        FAILED_TESTS=$(./sonobuoy --kubeconfig ${KUBECONFIG} e2e ${RESULTFILE} --show failed | grep "\[")
        echo -e "\n#####################################";
        echo -e "\ņ###### RESULT: ######################";
        echo -e "#####################################\n";
        ./sonobuoy --kubeconfig ${KUBECONFIG} e2e ${RESULTFILE};
        echo -e "\n#####################################\n";
        echo -e "Moving ${RESULTFILE} ./results"
        mkdir -p results && mv ${RESULTFILE} ./results
        kubectl version > ./results/k8s.version
        if [ -z "$FAILED_TESTS" ]; then
            exit 0;
        else
            exit 1;
        fi;
    fi;
done;
