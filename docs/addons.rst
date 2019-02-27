======
Addons
======

Dex
---

`Dex <https://github.com/dexidp/dex>`_ is an identity service that uses 
`OpenID Connect <https://openid.net/connect/>`_ to drive authentication for other apps. It can 
be used to authenticate against `OAuth2 <https://oauth.net/2/>`_ compatible apps such as Gitlab or
LDAP and then use this for further authentication, for example against the Kubernetes API.
This tutorial explains how to deploy Dex with koris on OpenStack. 

Prerequisites
^^^^^^^^^^^^^

Before starting, make sure koris is installed (see :doc:`installation`) and OpenStack is configured properly
(see :ref:`prepare-openstack`). Most importantly, you will need to deploy your cluster in a network that is
able to reach your identity provider.

Configuration
^^^^^^^^^^^^^

First create your koris config under ``configs/test-dex.yml``:

.. code-block:: yaml

    master_flavor: 'ECS.GP1.2-8'
    node_flavor: 'ECS.C1.4-8'
    # Adjust this according to your environment
    private_net: 
      name: 'your-net'
      subnet: 
        name: 'your-subnet'
        cidr: '10.32.192.0/24'
        router:
        name: 'your-router'

    cluster-name: 'test-dex'
    availibility-zones:
    - de-nbg6-1b
    - de-nbg6-1a
    n-masters: 1
    n-nodes: 1
    keypair: 'your-keypair'
    user_data: 'cloud-init-parts/generic'
    image: "your-image"
    loadbalancer:
    # For Dex you MUST give a Floating IP. Below is used as an example,
    # substitute with your Floating IP.
      floatingip: 10.36.60.232 
    certificates:
      expriry: 8760h
    storage_class: "PI-Storage-Class"
    pod_subnet: "10.233.0.0/16"
    pod_network: "CALICO"
    # Configuration block for Dex
    addons:
      dex:
        username_claim: email     
        groups_claim: groups
        # LB-Listener and K8s-Service ports for Dex
        ports:
        listener: 32000
        service: 32000
        # Configuration parameters for an OAuth2 application that is
        # deployed into the cluster
        client:
        id: example-app
        # LB-Listener and K8s-Service ports for the OAuth2 application
        ports:
            listener: 5555
            service: 32555

In this example we will use the IP **10.36.60.232** for our LoadBalancer. When this IP shows up from now on, substitute it with
your IP. Dex will then be reachable on port **32000** and the Dex `example-app <https://github.com/obitech/dex-example-app>`_ 
reachable on port **5555**. Clients can contact the example-app which will request an OIDC token from Dex. 

As an example we will be using Gitlab as an identity provider, but any other compatible provider will work as well
(for more info on how to configure Dex for other connectors, please consult the 
`official documentation <https://github.com/dexidp/dex/tree/master/Documentation/connectors>`_). Head to Gitlab under 
**Settings -> Applications** and create a new application with the following settings and scopes:

============  =======================================
Parameter     Value
============  =======================================
Name          dex
Redirect URI  ``https://10.36.60.232:32000/callback``
read_user     set
openid        set
============  =======================================

After saving, Gitlab will provide you with an **Application ID** (its value followingly known as **app-id**) and **Secret** 
(its value followingly known as **app-secret**). Make sure to copy those for later. 

Deployment
^^^^^^^^^^

Next, deploy your cluster, wait for it to be created and then source your kubeconfig:

.. code:: shell
    
    $ koris apply configs/test-dex.yml
    # ...
    $ export KUBECONFIG=test-dex-admin.conf

Before configuring Dex, deploy the certificates as secrets into the cluster:

.. code:: shell

    $ kubectl create secret tls dex.tls \
    >    --cert=certs-test-dex/dex-client.pem \
    >    --key=certs-test-dex/dex-client-key.pem
    $ kubectl create secret generic dex.root-ca \
    >    --from-file=certs-test-dex/dex-ca.pem

Then deploy the **app-id** and **app-secret** as secrets into the cluster (make sure to substitute):

.. code:: shell
    
    $ kubectl create secret generic gitlab-client \
    >    --from-literal=client-id=app-id \
    >    --from-literal=client-secret=app-secret

Afterwards adjust the Dex deployment in ``addons/dex/00-dex.yaml``:

.. code-block:: yaml

    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      labels:
        app: dex
      name: dex
    spec:
        # ...
        spec:
          serviceAccountName: dex
          containers:
            # ...
            env:
            - name: GITLAB_CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: gitlab-client
                  key: client-id
            - name: GITLAB_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: gitlab-client
                  key: client-secret
            volumes:
            - name: config
              configMap:
                name: dex
                items:
                - key: config.yaml
                  path: config.yaml
            - name: tls
              secret:
                # The secret that was just created
                secretName: dex.tls
    ---
    kind: ConfigMap
    apiVersion: v1
    metadata:
      name: dex
    data:
      config.yaml: |
        # Enter your IP here
        issuer: https://10.36.60.232:32000
        storage:
          type: kubernetes
          config:
            inCluster: true
        web:
          https: 0.0.0.0:5556
          tlsCert: /etc/dex/tls/tls.crt
          tlsKey: /etc/dex/tls/tls.key
        connectors:
          - type: gitlab
            id: gitlab
            name: Gitlab
            config:
              baseURL: https://gitlab.com
              # Enter your app-id and app-secret
              clientID: <app-id>
              clientSecret: <app-secret>
              # Enter your IP here
              redirectURI: https://10.36.60.232:32000/callback
        oauth2:
          skipApprovalScreen: true
        staticClients:
        - id: example-app
          redirectURIs:
          # Enter your IP here
          - 'http://10.36.60.232:5555/callback'
          name: 'Example App'
          secret: ZXhhbXBsZS1hcHAtc2VjcmV0
        enablePasswordDB: true
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: dex
    spec:
      type: NodePort
      ports:
      - name: dex
        port: 5556
        protocol: TCP
        targetPort: 5556
        nodePort: 32000
      selector:
        app: dex
    ---
    # ...

Deploy Dex into the cluster:

.. code:: shell

    $ kubectl create -f addons/00-dex.yaml

Then configure the example-app via ``addons/dex/01-example-app.yml``:

.. code:: yaml

    kind: Service
    apiVersion: v1
    metadata:
      name:  dex-example-app
      labels:
        app: dex-example-app
    spec:
      selector:
        app:  dex-example-app
      type:  NodePort
      ports:
      - name: callback
        port:  5555
        nodePort: 32555
        targetPort:  http
    ---
    apiVersion: extensions/v1beta1
    kind: Deployment
    metadata:
      labels:
        app: dex-example-app
      name: dex-example-app
    spec:
      replicas: 1
      template:
        metadata:
          labels:
            app: dex-example-app
        spec:
          containers:
          - name: dex-example-app
            image: obitech/dex-example-app
            # Enter your IP here for issuer and redirect
            args: ["--issuer", "https://10.36.60.232:32000",
              "--issuer-root-ca", "/etc/dex/tls/dex-ca.pem",
              "--listen", "http://0.0.0.0:5555",
              "--redirect-uri", "http://10.36.60.232:5555/callback"]
            ports:
            - name: http
              containerPort: 5555
            volumeMounts:
            - name: root-ca
              mountPath: /etc/dex/tls
          volumes:
          - name: root-ca
            secret:
              # The secret that was just created
              secretName: dex.root-ca

And deploy it: 

.. code:: shell

    $ kubectl create -f addons/dex/01-example-app.yml

Afterwards, open your browser and head to http://10.36.60.232:5555, click on **Login**, allow
the exception. Then click on **Login in with Gitlab**, which will redirect to Gitlab and ask for
authorization. After accepting and a short wait, an ID token is returned that can be used to 
authenticate against the API server:

.. code:: shell

    $ token='( ID token )'
    $ curl --http1.1 -H "Authorization: Bearer $token" -k https://10.36.60.232:6443/api/v1/nodes

The request will fail, since no (Cluster)RoleBinding has been created yet. In order to give your user
cluster admin privileges, edit the ``addons/02-clusterrolebinding.yml`` and enter the Email address you
have used for Gitlab:

.. code-block:: yaml

    kind: ClusterRoleBinding
    apiVersion: rbac.authorization.k8s.io/v1
    metadata:
      name: your-user-binding
    roleRef:
      apiGroup: rbac.authorization.k8s.io
      kind: ClusterRole
      name: cluster-admin
    subjects:
    - kind: User
      name: your-gitlab-user-email@example.com

Then deploy it into the cluster:

.. code:: shell
    
    $ kubectl create -f addons/dex/02-clusterrolebinding.yml

Now send the request again:

.. code:: shell

    $ curl --http1.1 -H "Authorization: Bearer $token" -k https://10.36.60.232:6443/api/v1/nodes
    {
        "kind": "NodeList",
        "apiVersion": "v1",
    # ...

Cleanup
^^^^^^^

To remove Dex, delete all manifests:

.. code:: shell

    $ kubectl destroy -f addons/dex/

Then delete all secrets:

.. code:: shell

    $ kubectl destroy secret dex.tls dex.root-ca gitlab-client
