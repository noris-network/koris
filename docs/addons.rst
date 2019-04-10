======
Addons
======

Dex
---

.. note::
  This feature is currently in beta; your mileage may vary and documentation is expected to change.

`Dex <https://github.com/dexidp/dex>`_ is an identity service that uses
`OpenID Connect <https://openid.net/connect/>`_ to drive authentication for other apps. It can
be used to authenticate against `OAuth2 <https://oauth.net/2/>`_ compatible apps such as Gitlab or
LDAP and then use this for further authentication, for example against the Kubernetes API.
This tutorial explains how to deploy Dex with koris on OpenStack.

From the `dex documentation <https://github.com/dexidp/dex#connectors>`_:

  When a user logs in through dex, the user's identity is usually stored in another user-management system:
  a LDAP directory, a GitHub org, etc. Dex acts as a shim between a client app and the upstream identity provider.
  The client only needs to understand OpenID Connect to query dex, while dex implements an array of protocols for
  querying other user-management systems.

  .. image:: static/_imgs/dex-flow.png
    :align: center
    :scale: 60%
    :alt: Dex flow as described on in the official documentation

For more information on how Dex works with OpenID Connect and OAuth2,
see: `"An overview of OpenID Connect" <https://github.com/dexidp/dex/blob/master/Documentation/openid-connect.md>`_

In this tutorial we will use Gitlab to authenticate our user against a koris cluster:

1. Setup Gitlab OAuth Authentication
2. Configure koris to use dex
3. Deploy & configure a Kubernetes cluster with koris
4. Deploy Dex and a client application for authentication against the cluster.

Prerequisites
^^^^^^^^^^^^^

General
=======

Before starting, make sure koris is installed (see :doc:`installation`) and OpenStack is configured properly
(see :ref:`prepare-openstack`). Most importantly, you will need to deploy your cluster in a network that is
able to reach your identity provider.

Additionally, create a *Floating IP* in OpenStack. This will be the address to reach your cluster. In the following
tutorial there will be values marked as ``%%FLOATING_IP%%``. **When you see this placeholder in this tutorial,
substitute it with the Floating IP that you created in OpenStack.**

Gitlab
======

This tutorial will use Gitlab as an Identity Provider, but it should work with any
`compatible connector <https://github.com/dexidp/dex/tree/master/Documentation/connectors>`_. Before getting started with
Dex, set up a *Application ID* and *Secret* on Gitlab:

1. Go to your **Gitlab User Settings** and click on **Applications**
2. Create a new Application with the following parameters:

============  ====================================
Parameter     Value
============  ====================================
Name          dex
Redirect URI  ``https://%%FLOATING_IP%%/callback``
read_user     set
openid        set
============  ====================================

Example:

.. image:: static/_imgs/gl_oauth.png

3. After clicking **Save application**,  the *Application ID* and *Secret* are visible, which will be further referenced
as ``%%APP_ID%%`` and ``%%APP_SECRET%%``. **When you see either of those placeholders in this tutorial, substitute them
with the value provided from Gitlab.**

Example:

.. image:: static/_imgs/gl_oauth2.png

Configuration
^^^^^^^^^^^^^

Next create your koris config under the name ``test-dex.yml``:

.. code-block:: yaml

    master_flavor: 'ECS.GP1.2-8'
    node_flavor: 'ECS.GP1.2-8'

    # Adjust below according to your environment
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
    user_data: 'cloud-init-parts/generic'

    # Substitute with the name of your keypair in OpenStack.
    keypair: 'your-keypair'

    # Substitute with the latest koris image available.
    image: "koris-2019-04-04"

    loadbalancer:
      # Substitute here
      floatingip: "%%FLOATING_IP%%"

    certificates:
      expriry: 8760h
    storage_class: "BSS-Performance-Storage"
    pod_subnet: "10.233.0.0/16"
    pod_network: "CALICO"

    addons:
      dex:
        username_claim: email
        groups_claim: groups
        ports:
          listener: 32000
          service: 32000
        client:
          id: example-app
          ports:
              listener: 5555
              service: 32555

In order to facilitate the Dex authentication flow, two Deployments will have to be created inside our Kubernetes cluster:
one for Dex and one for a client application. In the configuration file, the ``addons.dex`` block will define the basic
configuration that is required in order to prepare a cluster to use Dex.

`Claims <https://en.wikipedia.org/wiki/Claims-based_identity>`_ are specific attributes about
a user that the identity provider returns to the client application - in this case the Email and Groups the user
belongs to.

``addons.dex.ports`` defines the ``listener`` port on which the LoadBalancer on OpenStack listens to, and the
``service`` port on the Dex Kubernetes Service listens on. The OpenStack LoadBalancer will then forward any traffic that
comes in on ``%%FLOATING_IP%%:32000`` to ``node_ip:32000``.

The block ``addons.dex.client`` defines information about the client application that requests authentication from Dex. In
this tutorial, the official `example-app <https://github.com/obitech/dex-example-app>`_ is used, which has to be registered
with Dex. *There can only be a single client application registered with Dex*, however
`cross-client trust <https://github.com/dexidp/dex/blob/master/Documentation/custom-scopes-claims-clients.md#cross-client-trust-and-authorized-party>`_
is possible.

Similar to the enclosing block, ``addons.dex.client.ports`` defines the value for the LoadBalancer ``listener`` port of the client
application, as well as the Kubernetes ``service`` port.

Deployment
^^^^^^^^^^

Next, deploy your cluster:

.. code:: shell

    $ koris apply test-dex.yml

Once it's ready, source your kubeconfig:

.. code:: shell

    $ export KUBECONFIG=test-dex-admin.conf

Before we deploy any resources, the SSL infrastructure has to be set up. Dex *needs* to run on HTTPS, which requires
a valid SSL certificate that is issued on ``%%FLOATING_IP%%``. Dex uses this certificate to sign ID Tokens it sends
to the client application, which in turn are used by the user in order to authenticate against the Kubernetes API Server.
The Kubernetes API Server has access to the Public Key the ID Token has been signed with, so it can verify that it was
indeed Dex that signed it. All necessary certificate files are generated in the folder ``certs-test-dex``
(following the syntax ``certs-<cluster-name>``).

We take those certificates, and deploy them as secrets into our cluster:

.. code:: shell

    $ kubectl create secret tls dex.tls \
        --cert=certs-test-dex/dex-client.pem \
        --key=certs-test-dex/dex-client-key.pem \
        --namespace=kube-system
    $ kubectl create secret generic dex.root-ca \
        --from-file=certs-test-dex/dex-ca.pem \
        --namespace=kube-system

Next we have to deploy the *Application ID* and *Secret* from Gitlab as Kubernetes secrets too. For easier copying,
we can export them as environment variables first. **Make sure to substitute
the placeholders below with your own**:

.. code:: shell

    $ export APP_ID="%%APP_ID%%"
    $ export APP_SECRET="%%APP_SECRET%%"

Then we can deploy it as a secret:

.. code:: shell

    $ kubectl create secret generic gitlab-client \
        --from-literal=client-id=$APP_ID \
        --from-literal=client-secret=$APP_SECRET \
        --namespace=kube-system

Afterwards we can create the deployments for Dex and the client application. All files are located in
``addons/dex`` and include numbered comments that refer to this tutorial. Before we edit those, Before, let's
create a local copy from the template files:

.. code:: shell

    $ mkdir -p manifests/
    $ cp -r addons/dex manifests

With local copies presents, let's edit ``manifests/dex/00-dex.yaml`` first. We go through the numbered comments in order:

.. code-block:: yaml

     # 1.1 Substitute this with your Floating IP
    issuer: https://%%FLOATING_IP%%:32000

    # 1.2 (Optional): Enter the URL of your Gitlab instance
    baseURL: https://gitlab.com

    # 1.3 he URL Gitlab redirects to. Substitute with with your Floating IP
    redirectURI: https://%%FLOATING_IP%%:32000/callback

    # 1.4 The URL where Dex redirects to. Substitute with with your Floating IP
    - 'http://%%FLOATING_IP%%:5555/callback'

With the manifest present, we can deploy Dex into the cluster:

.. code:: shell

    $ kubectl create -f addons/00-dex.yaml

We should verify everything is running as intended:

.. code:: shell

    $ kubectl get all -n kube-system -l k8s-app=dex
    NAME          TYPE       CLUSTER-IP     EXTERNAL-IP   PORT(S)          AGE
    service/dex   NodePort   10.99.212.63   <none>        5556:32000/TCP   86s

    NAME                  DESIRED   CURRENT   UP-TO-DATE   AVAILABLE   AGE
    deployment.apps/dex   1         1         1            1           86s


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

Afterwards, open your browser and head to http://10.36.60.232:5555,
click on **Login**, allow the exception. Then click on
**Login in with Gitlab**, which will redirect to Gitlab and ask for
authorization.
After accepting and a short wait, an ID token is returned that can be used to
authenticate against the API server:

.. code:: shell

    $ token='( ID token )'
    $ curl --http1.1 -H "Authorization: Bearer $token" -k https://10.36.60.232:6443/api/v1/nodes

The request will fail, since no (Cluster)RoleBinding has been created yet.
In order to give your user cluster admin privileges,
edit the ``addons/02-clusterrolebinding.yml`` and enter the Email address you
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
