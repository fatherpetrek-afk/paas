import streamlit as st

st.title("PaaS")
n = st.slider("n", 0, 10, 3)
st.write(n)
